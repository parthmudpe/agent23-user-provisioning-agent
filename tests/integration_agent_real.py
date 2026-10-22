"""REAL-system regression for 'Create a new user named agenttest with a home directory.'
A scripted model emits the bad output seen with llama3.2:3b (username inside groups, invented
groups, unknown tool JSON); real useradd/getent/id run underneath.
Run on a disposable machine:  sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_agent_real"""
import json
import os
import subprocess
import sys

from provisioning_agent.agent import Agent
from provisioning_agent.system_ops import SystemOps
from provisioning_agent.tools import Dispatcher
from tests.fakes import FakeClient


def sh(*c):
    return subprocess.run(c, capture_output=True, text=True)


def main():
    if os.environ.get("AGENT23_INTEGRATION") != "1" or os.geteuid() != 0:
        sys.exit("Refusing: set AGENT23_INTEGRATION=1 and run as root on a disposable machine.")
    sh("userdel", "-r", "agenttest"); sh("groupdel", "agenttest")
    try:
        ops = SystemOps(audit_path="logs/integration_audit.log")
        client = FakeClient([
            ("text", json.dumps({"name": "create_home_directory", "parameters": {"username": "agenttest"}})),
            {"tool_calls": [{"function": {"name": "create_user", "arguments": {
                "username": "agenttest", "groups": ["agenttest", "users", "home"],
                "home_directory": "/home/agenttest"}}}]},
            ("text", "Created agenttest."),
        ])
        out = Agent(client, Dispatcher(ops)).ask("Create a new user named agenttest with a home directory.")
        print("agent said:", out)
        passwd = sh("getent", "passwd", "agenttest").stdout.strip()
        print("getent:", passwd); print("id:", sh("id", "agenttest").stdout.strip())
        ok = bool(passwd) and os.path.isdir("/home/agenttest") and sh("getent", "group", "home").returncode != 0
        print("INTEGRATION", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        sh("userdel", "-r", "agenttest"); sh("groupdel", "agenttest")


if __name__ == "__main__":
    sys.exit(main())
