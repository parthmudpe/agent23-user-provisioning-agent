"""Regression tests for bugs found in review of the Ollama layer."""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from provisioning_agent import preflight
from provisioning_agent.agent import Agent
from provisioning_agent.ollama_client import OllamaClient
from provisioning_agent.system_ops import SystemOps
from provisioning_agent.tools import Dispatcher
from tests.fakes import FakeClient, FakeSystem


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                        shells_file="/nonexistent")
        self.disp = Dispatcher(ops)
        if os.getuid() >= 1000:
            self._uid = os.getuid()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _calls(self, *names):
        return [c[0] for c in self.fake.calls if c[0] in names]

    def test_two_directories_same_user_both_created(self):
        self.disp.execute("create_user", {"username": "ann"})
        client = FakeClient([
            {"tool_calls": [
                {"function": {"name": "create_directory",
                              "arguments": {"username": "ann", "relative_path": "docs"}}},
                {"function": {"name": "create_directory",
                              "arguments": {"username": "ann", "relative_path": "work"}}},
            ]},
            ("text", "done"),
        ])
        Agent(client, self.disp).ask("make docs and work for ann")
        self.assertEqual(len(self._calls("runuser")), 2)

    def test_shell_change_then_lock_both_applied(self):
        self.disp.execute("create_user", {"username": "bo"})
        client = FakeClient([
            {"tool_calls": [
                {"function": {"name": "modify_user", "arguments": {"username": "bo", "shell": "/bin/bash"}}},
                {"function": {"name": "modify_user", "arguments": {"username": "bo", "lock": True}}},
            ]},
            ("text", "done"),
        ])
        Agent(client, self.disp).ask("x")
        self.assertEqual(len(self._calls("usermod")), 2)

    def test_invalid_user_does_not_create_orphan_group(self):
        client = FakeClient([
            ("tool", "create_user", {"username": "BAD NAME", "groups": ["newteam"]}),
            ("text", "invalid"),
        ])
        Agent(client, self.disp).ask("x")
        self.assertNotIn("newteam", self.fake.groups)
        self.assertEqual(self._calls("groupadd"), [])

    def test_existing_user_does_not_create_orphan_group(self):
        self.disp.execute("create_user", {"username": "cy"})
        client = FakeClient([
            ("tool", "create_user", {"username": "cy", "groups": ["newteam"]}),
            ("text", "exists"),
        ])
        Agent(client, self.disp).ask("x")
        self.assertNotIn("newteam", self.fake.groups)

    def test_malformed_tool_calls_do_not_crash(self):
        for bad in ([None], ["create_user"], [{"function": None}], [{"function": "x"}]):
            client = FakeClient([{"tool_calls": bad}, ("text", "ok?")])
            out = Agent(client, self.disp).ask("x")
            self.assertEqual(out, "ok?")

    def test_dry_run_keeps_history_consistent(self):
        ops = SystemOps(runner=self.fake, dry_run=True, is_root=lambda: False,
                        home_root=self.tmp, shells_file="/nonexistent")
        agent = Agent(FakeClient([{"tool_calls": [
            {"function": {"name": "create_group", "arguments": {"groupname": "g1"}}},
            {"function": {"name": "create_group", "arguments": {"groupname": "g2"}}},
        ]}]), Dispatcher(ops))
        out = agent.ask("x")
        self.assertIn("g1", out)
        self.assertIn("g2", out)
        n_calls = len(agent.messages[-3]["tool_calls"]) if agent.messages[-3].get("tool_calls") else 0
        n_tools = sum(1 for m in agent.messages if m["role"] == "tool")
        self.assertEqual(n_calls, n_tools)

    def test_unverified_success_claim_is_flagged(self):
        out = Agent(FakeClient([("text", "I created user eve."), ("text", "I created user eve.")]),
                    self.disp).ask("create eve")
        self.assertNotIn("eve", self.fake.users)
        self.assertIn("no tool was run", out.lower())

    def test_request_options_set(self):
        client = FakeClient([("text", "hi?")])
        Agent(client, self.disp).ask("hello")
        opts = client.requests[0].get("options", {})
        self.assertEqual(opts.get("temperature"), 0)
        self.assertGreaterEqual(opts.get("num_ctx", 0), 8192)

    def test_ollama_host_without_scheme(self):
        self.assertEqual(OllamaClient("127.0.0.1:11434").host, "http://127.0.0.1:11434")
        self.assertEqual(OllamaClient("0.0.0.0").host, "http://0.0.0.0:11434")
        self.assertEqual(OllamaClient("http://h:1/").host, "http://h:1")

    def test_preflight_honours_selected_model_and_host(self):
        with mock.patch.dict(os.environ, {"OLLAMA_MODEL": "qwen2.5:7b"}), \
             mock.patch.object(preflight, "_ollama_status", return_value=(True, ["qwen2.5:7b"])):
            r = preflight.check()
            self.assertTrue(r["model_ok"])
        with mock.patch.dict(os.environ, {"OLLAMA_HOST": "10.0.0.5:11434"}):
            self.assertEqual(preflight.ollama_host(), "http://10.0.0.5:11434")


if __name__ == "__main__":
    unittest.main()
