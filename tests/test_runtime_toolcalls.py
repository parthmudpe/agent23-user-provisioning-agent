"""Regression tests for: 'Create a new user named agenttest with a home directory.'
-> hallucinated groups, useradd exit 9, and 'Unsupported tool-call format'."""
import json
import os
import shutil
import tempfile
import unittest

from provisioning_agent import agent as agent_mod
from provisioning_agent.agent import Agent
from provisioning_agent.system_ops import SystemOps
from provisioning_agent.tools import Dispatcher
from tests.fakes import FakeClient, FakeSystem

REQ = "Create a new user named agenttest with a home directory."


def call(name, **args):
    return {"function": {"name": name, "arguments": args}}


class RuntimeToolCallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                             shells_file="/nonexistent")
        self.disp = Dispatcher(self.ops)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_agent(self, script, request=REQ, disp=None):
        client = FakeClient(script)
        out = Agent(client, disp or self.disp).ask(request)
        return out, client

    def cmds(self, name):
        return [c for c in self.fake.calls if c[0] == name]

    def test_username_in_groups_does_not_break_useradd(self):
        out, _ = self.run_agent([
            {"tool_calls": [call("create_user", username="agenttest", groups=["agenttest"])]},
            ("text", "Created agenttest."),
        ])
        self.assertIn("agenttest", self.fake.users)
        self.assertEqual(self.cmds("groupadd"), [])
        self.assertNotIn("-G", self.cmds("useradd")[0])

    def test_unrequested_groups_are_ignored(self):
        self.run_agent([
            {"tool_calls": [call("create_user", username="agenttest", groups=["users", "home", "sudo"],
                                 home_directory="/home/agenttest", create_home=True)]},
            ("text", "done"),
        ])
        self.assertEqual(self.cmds("groupadd"), [])
        self.assertNotIn("-G", self.cmds("useradd")[0])
        self.assertIn("agenttest", self.fake.users)

    def test_requested_groups_are_kept(self):
        self.run_agent([
            {"tool_calls": [call("create_user", username="bob", groups=["developers"])]},
            ("text", "done"),
        ], request="create user bob in the developers group")
        self.assertIn("developers", self.fake.users["bob"]["groups"])

    def test_requested_missing_group_still_created(self):
        self.run_agent([
            {"tool_calls": [call("create_user", username="cat", groups=["qa"])]},
            ("text", "done"),
        ], request="create user cat in group qa")
        self.assertIn("qa", self.fake.groups)
        self.assertIn("qa", self.fake.users["cat"]["groups"])

    def test_custom_home_directory_is_rejected(self):
        out, client = self.run_agent([
            {"tool_calls": [call("create_user", username="dan", home_directory="/srv/dan")]},
            ("text", "cannot do that"),
        ], request="create user dan with home /srv/dan")
        self.assertNotIn("dan", self.fake.users)
        self.assertEqual(self.cmds("useradd"), [])
        tool_msg = [m for m in client.requests[1]["messages"] if m["role"] == "tool"][0]
        self.assertTrue(json.loads(tool_msg["content"])["is_error"])

    def test_unknown_tool_json_gets_feedback_not_abort(self):
        out, client = self.run_agent([
            ("text", json.dumps({"name": "create_home_directory", "parameters": {"username": "agenttest"}})),
            {"tool_calls": [call("create_user", username="agenttest")]},
            ("text", "Created agenttest."),
        ])
        self.assertEqual(out, "Created agenttest.")
        self.assertIn("agenttest", self.fake.users)
        feedback = client.requests[1]["messages"][-1]
        self.assertEqual(feedback["role"], "user")
        self.assertIn("create_user", feedback["content"])

    def test_string_encoded_parameters_are_accepted(self):
        payload = {"name": "create_user", "parameters": json.dumps({"username": "agenttest"})}
        out, _ = self.run_agent([("text", json.dumps(payload)), ("text", "ok")])
        self.assertIn("agenttest", self.fake.users)

    def test_openai_style_wrapper_is_accepted(self):
        payload = {"type": "function", "function": {"name": "create_user", "arguments": {"username": "agenttest"}}}
        self.run_agent([("text", "```json\n" + json.dumps(payload) + "\n```"), ("text", "ok")])
        self.assertIn("agenttest", self.fake.users)

    def test_persistent_garbage_still_stops_safely(self):
        bad = ("text", json.dumps({"name": "rm_rf", "parameters": {}}))
        out, _ = self.run_agent([bad, bad, bad, bad])
        self.assertIn("Unsupported tool-call format", out)
        self.assertEqual(self.fake.calls, [])

    def test_prose_is_never_treated_as_tool_call(self):
        out, _ = self.run_agent([("text", "Which username should I use?")])
        self.assertEqual(out, "Which username should I use?")

    def test_dry_run_plan_has_no_invented_groups(self):
        ops = SystemOps(runner=self.fake, dry_run=True, is_root=lambda: False, home_root=self.tmp,
                        shells_file="/nonexistent")
        out, _ = self.run_agent([
            {"tool_calls": [call("create_user", username="agenttest", groups=["agenttest", "audio"])]},
        ], disp=Dispatcher(ops))
        self.assertIn("DRY RUN", out)
        self.assertIn("useradd -m", out)
        self.assertNotIn("-G", out)
        self.assertNotIn("agenttest", self.fake.users)

    def test_extra_unknown_arguments_are_dropped_and_reported(self):
        out, client = self.run_agent([
            {"tool_calls": [call("create_user", username="eve2", password="hunter2", uid=0)]},
            ("text", "done"),
        ])
        tool_msg = [m for m in client.requests[1]["messages"] if m["role"] == "tool"][0]
        res = json.loads(tool_msg["content"])["result"]
        self.assertEqual(sorted(res["ignored_arguments"]), ["password", "uid"])
        self.assertNotIn("hunter2", json.dumps(self.fake.calls))


if __name__ == "__main__":
    unittest.main()


class GroupMentionTests(unittest.TestCase):
    def named(self, request, group):
        a = Agent(FakeClient([]), Dispatcher(SystemOps(runner=FakeSystem("/tmp"), is_root=lambda: True)))
        a._requests = [request]
        args = {"username": "u1", "groups": [group]}
        return a._sanitize_group_args("create_user", args) == []

    def test_group_context_phrases(self):
        for req, g in [("create user bob in developers", "developers"),
                       ("create user bob in the developers group", "developers"),
                       ("create user bob in group qa", "qa"),
                       ("create user bob in groups dev, ops", "ops"),
                       ("add bob to the sudo group", "sudo"),
                       ("make bob a member of docker", "docker"),
                       ("put bob into sudo and docker", "docker")]:
            self.assertTrue(self.named(req, g), (req, g))

    def test_plain_words_are_not_groups(self):
        for req, g in [("Create a new user named agenttest with a home directory.", "home"),
                       ("Create user bob with a home directory", "users"),
                       ("create user bob", "sudo")]:
            self.assertFalse(self.named(req, g), (req, g))


class ObservedFailureTests(unittest.TestCase):
    """Exact llama3.2:3b output seen on the user's machine (dry-run, 'agenttest')."""
    BAD = ("Since the user 'agenttest' already exists, I will check if the user's home directory "
           "exists. If not, I will create it.\n\n"
           '{"name": "test", "parameters": {"path": "/home/agenttest"}}')

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                             shells_file="/nonexistent")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_prose_plus_bogus_json_is_corrected_then_executed(self):
        client = FakeClient([("text", self.BAD),
                             {"tool_calls": [call("create_user", username="agenttest")]},
                             ("text", "Created agenttest.")])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertEqual(out, "Created agenttest.")
        self.assertIn("agenttest", self.fake.users)
        self.assertEqual(client.requests[1]["messages"][-1]["role"], "user")

    def test_tool_less_hallucination_is_nudged_once_then_flagged(self):
        claim = ("text", "The user 'agenttest' already exists.")
        client = FakeClient([claim, claim])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertEqual(len(client.requests), 2)
        self.assertTrue(out.startswith("[Warning: no tool was run"))
        self.assertEqual(self.fake.calls, [])

    def test_nudge_leads_to_real_tool_use(self):
        client = FakeClient([("text", "The user already exists."),
                             {"tool_calls": [call("get_user_info", username="agenttest")]},
                             ("text", "agenttest does not exist.")])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertEqual(out, "agenttest does not exist.")
        self.assertIn(["getent", "passwd", "agenttest"], self.fake.calls)

    def test_dry_run_never_executes_through_nudge_path(self):
        ops = SystemOps(runner=self.fake, dry_run=True, is_root=lambda: False, home_root=self.tmp,
                        shells_file="/nonexistent")
        client = FakeClient([("text", self.BAD),
                             {"tool_calls": [call("create_user", username="agenttest")]}])
        out = Agent(client, Dispatcher(ops)).ask(REQ)
        self.assertIn("DRY RUN", out)
        self.assertNotIn("agenttest", self.fake.users)


class ConstrainedRepairTests(unittest.TestCase):
    BAD = ObservedFailureTests.BAD

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                             shells_file="/nonexistent")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_bad_output_repaired_into_real_tool_call(self):
        client = FakeClient([("text", self.BAD), ("text", "Created agenttest.")],
                            format_script=[json.dumps({"tool": "create_user",
                                                       "arguments": {"username": "agenttest"}})])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertEqual(out, "Created agenttest.")
        self.assertIn("agenttest", self.fake.users)
        req = client.format_requests[0]
        self.assertIn("create_user", req["format"]["properties"]["tool"]["enum"])
        self.assertNotIn("tools", req)            # constrained call has no free-form tools
        self.assertEqual(len(client.format_requests), 1)  # repair is attempted once per turn

    def test_repaired_call_still_sanitised_and_validated(self):
        client = FakeClient([("text", "nope"), ("text", "done?")],
                            format_script=[json.dumps({"tool": "create_user", "arguments": {
                                "username": "agenttest", "groups": ["agenttest"], "password": "x"}})])
        Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertNotIn("-G", [c for c in self.fake.calls if c[0] == "useradd"][0])
        self.assertNotIn("x", [a for c in self.fake.calls for a in c if a == "x"])

    def test_repaired_call_goes_through_validation(self):
        client = FakeClient([("text", "nope"), ("text", "invalid?")],
                            format_script=[json.dumps({"tool": "create_user",
                                                       "arguments": {"username": "BAD NAME"}})])
        Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertEqual(self.fake.calls, [])

    def test_repair_reply_for_questions(self):
        client = FakeClient([("text", "hello there")],
                            format_script=[json.dumps({"tool": "reply",
                                                      "arguments": {"message": "Which username?"}})])
        out = Agent(client, Dispatcher(self.ops)).ask("hi")
        self.assertEqual(out, "Which username?")

    def test_repair_dry_run_is_safe(self):
        ops = SystemOps(runner=self.fake, dry_run=True, is_root=lambda: False, home_root=self.tmp,
                        shells_file="/nonexistent")
        client = FakeClient([("text", self.BAD)],
                            format_script=[json.dumps({"tool": "create_user",
                                                       "arguments": {"username": "agenttest"}})])
        out = Agent(client, Dispatcher(ops)).ask(REQ)
        self.assertIn("DRY RUN", out)
        self.assertEqual([c for c in self.fake.calls if c[0] in ("useradd", "groupadd")], [])

    def test_garbage_repair_falls_back_to_unsupported_with_snippet(self):
        bad = ("text", self.BAD)
        client = FakeClient([bad, bad, bad, bad],
                            format_script=["not json at all"])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertIn("Unsupported tool-call format", out)
        self.assertIn("Last model output", out)
        self.assertEqual(self.fake.calls, [])

    def test_unknown_tool_in_repair_is_rejected(self):
        bad = ("text", self.BAD)
        client = FakeClient([bad, bad, bad, bad],
                            format_script=[json.dumps({"tool": "rm_rf", "arguments": {}})])
        out = Agent(client, Dispatcher(self.ops)).ask(REQ)
        self.assertIn("Unsupported tool-call format", out)

    def test_trace_receives_raw_output(self):
        seen = []
        client = FakeClient([("text", "what?")])
        a = Agent(client, Dispatcher(self.ops)); a.trace = seen.append
        a.ask("x")
        self.assertTrue(any("what?" in s for s in seen))


class LoopHandlingTests(unittest.TestCase):
    """Real log: user already existed; model kept re-issuing create_user until the step limit."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                             shells_file="/nonexistent")
        self.disp = Dispatcher(self.ops)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_existing_user_reports_error_instead_of_looping(self):
        self.disp.execute("create_user", {"username": "agenttest"})
        before = len(self.fake.calls)
        same = {"tool_calls": [call("create_user", username="agenttest", home_directory="/home/agenttest")]}
        client = FakeClient([same] * 8)
        out = Agent(client, self.disp).ask(REQ)
        self.assertIn("already exists", out)
        self.assertIn("No further action", out)
        self.assertLessEqual(len(client.requests), 3)
        self.assertEqual([c for c in self.fake.calls[before:] if c[0] in ("useradd", "groupadd")], [])

    def test_repeat_after_success_returns_verified_summary(self):
        same = {"tool_calls": [call("create_user", username="agenttest")]}
        client = FakeClient([same] * 5)
        out = Agent(client, self.disp).ask(REQ)
        self.assertTrue(out.startswith("Done. Verified:"))
        self.assertEqual(len([c for c in self.fake.calls if c[0] == "useradd"]), 1)

    def test_tool_name_aliases(self):
        self.disp.execute("create_user", {"username": "agenttest"})
        bad = ("text", 'Checking.\n\n{"name": "get_user", "parameters": {"username": "agenttest"}}')
        client = FakeClient([bad, ("text", "agenttest exists.")])
        out = Agent(client, self.disp).ask("does agenttest exist")
        self.assertEqual(out, "agenttest exists.")

    def test_step_limit_message_includes_last_error(self):
        looping = [{"tool_calls": [call("get_user_info", username=f"u{i}")]} for i in range(15)]
        out = Agent(FakeClient(looping), self.disp).ask("x")
        self.assertIn("step limit", out.lower())


class ObservedRunTests(unittest.TestCase):
    """Bugs seen in the user's real session: show/lock."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                        shells_file="/nonexistent")
        self.disp = Dispatcher(ops)
        self.disp.execute("create_user", {"username": "demo1"})
        self.fake.calls.clear()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_show_user_prints_details_when_model_repeats_lookup(self):
        same = {"tool_calls": [call("get_user_info", username="demo1")]}
        out = Agent(FakeClient([same] * 5), self.disp).ask("show me demo1")
        self.assertIn("User demo1: uid", out)
        self.assertIn("locked:", out)
        self.assertIn("home", out)

    def test_string_booleans_are_accepted(self):
        client = FakeClient([{"tool_calls": [call("modify_user", username="demo1", lock="true")]},
                             ("text", "locked?")])
        Agent(client, self.disp).ask("lock demo1")
        self.assertIn("-L", [c for c in self.fake.calls if c[0] == "usermod"][0])

    def test_conflicting_lock_unlock_only_first_applied(self):
        self.fake.users["demo1"]["locked"] = False
        client = FakeClient([{"tool_calls": [call("modify_user", username="demo1", lock="true"),
                                             call("modify_user", username="demo1", lock="false")]},
                             ("text", "locked?")])
        Agent(client, self.disp).ask("lock demo1")
        usermods = [c for c in self.fake.calls if c[0] == "usermod"]
        self.assertEqual(len(usermods), 1)
        self.assertIn("-L", usermods[0])
        self.assertTrue(self.fake.users["demo1"]["locked"])

    def test_get_user_info_reports_lock_state(self):
        res, err = self.disp.execute("get_user_info", {"username": "demo1"})
        self.assertFalse(err)
        self.assertIn("locked", res["user"])

    def test_group_and_list_rendering(self):
        same = {"tool_calls": [call("list_users")]}
        out = Agent(FakeClient([same] * 5), self.disp).ask("list users")
        self.assertIn("demo1", out)
