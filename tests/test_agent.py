import json
import shutil
import tempfile
import unittest

from provisioning_agent.agent import Agent, ollama_tool_schemas
from provisioning_agent.system_ops import SystemOps
from provisioning_agent.tools import TOOLS, Dispatcher
from tests.fakes import FakeClient, FakeSystem


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        ops = SystemOps(
            runner=self.fake,
            is_root=lambda: True,
            home_root=self.tmp,
            shells_file="/nonexistent",
        )
        self.disp = Dispatcher(ops)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_schemas_well_formed(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertEqual(len(names), len(TOOLS))

        schemas = ollama_tool_schemas()
        self.assertEqual(len(schemas), len(TOOLS))

        for tool in schemas:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertEqual(
                tool["function"]["parameters"]["type"], "object"
            )

    def test_tool_loop_end_to_end(self):
        client = FakeClient([
            ("tool", "create_user", {
                "username": "zoe",
                "groups": ["developers"],
            }),
            ("text", "Created zoe, verified."),
        ])

        agent = Agent(client, self.disp, model="test-model")
        out = agent.ask("make user zoe in developers")

        self.assertEqual(out, "Created zoe, verified.")
        self.assertIn("zoe", self.fake.users)

        # The second request must include the assistant tool call and
        # the corresponding tool result.
        history = client.requests[1]["messages"]
        self.assertEqual(history[-2]["role"], "assistant")
        self.assertEqual(
            history[-2]["tool_calls"][0]["function"]["name"],
            "create_user",
        )
        self.assertEqual(history[-1]["role"], "tool")

        tool_result = json.loads(history[-1]["content"])
        self.assertFalse(tool_result["is_error"])
        self.assertTrue(tool_result["result"]["verified"])

    def test_error_returned_to_model(self):
        client = FakeClient([
            ("tool", "create_user", {"username": "BAD NAME"}),
            ("text", "The username is invalid."),
        ])

        out = Agent(client, self.disp).ask("create an invalid user")
        self.assertEqual(out, "The username is invalid.")

        history = client.requests[1]["messages"]
        self.assertEqual(history[-1]["role"], "tool")

        tool_result = json.loads(history[-1]["content"])
        self.assertTrue(tool_result["is_error"])
        self.assertIn("Validation failed", str(tool_result["result"]))
        self.assertEqual(self.fake.calls, [])

    def test_unknown_tool_and_step_limit(self):
        result, is_error = self.disp.execute("rm_rf", {})
        self.assertTrue(is_error)

        looping = [
            ("tool", "list_users", {})
            for _ in range(20)
        ]
        out = Agent(FakeClient(looping), self.disp).ask("loop")
        self.assertTrue(any(k in out.lower() for k in ("step limit", "repeating the same call", "no regular users")), out)


if __name__ == "__main__":
    unittest.main()
