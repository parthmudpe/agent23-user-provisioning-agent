"""In-memory Linux simulator and scripted Ollama client for unit tests."""
import json
import os

from provisioning_agent.system_ops import CommandResult


class FakeSystem:
    def __init__(self, home_root):
        self.home_root = home_root
        self.users = {}
        self.groups = {"users": 100, "sudo": 27, "developers": 2001}
        self.next_uid = 1000
        self.calls = []
        self.users["root"] = dict(
            uid=0, gid=0, comment="root", home="/root",
            shell="/bin/bash", groups=["root"], locked=False,
        )

    def _passwd(self, n):
        u = self.users[n]
        return (
            f"{n}:x:{u['uid']}:{u['gid']}:{u['comment']}:"
            f"{u['home']}:{u['shell']}"
        )

    def __call__(self, cmd):
        self.calls.append(cmd)
        c = cmd[0]

        if c == "getent":
            db = cmd[1]
            if db == "passwd":
                if len(cmd) == 2:
                    return CommandResult(
                        0, "\n".join(self._passwd(n) for n in self.users)
                    )
                return (
                    CommandResult(0, self._passwd(cmd[2]))
                    if cmd[2] in self.users else CommandResult(2)
                )
            if db == "group":
                n = cmd[2]
                if n not in self.groups:
                    return CommandResult(2)
                members = ",".join(
                    u for u, d in self.users.items() if n in d["groups"]
                )
                return CommandResult(
                    0, f"{n}:x:{self.groups[n]}:{members}"
                )
            if db == "shadow":
                n = cmd[2]
                if n not in self.users:
                    return CommandResult(2)
                marker = "!" if self.users[n]["locked"] else "*"
                return CommandResult(
                    0, f"{n}:{marker}:19000:0:99999:7:::"
                )

        if c == "id":
            n = cmd[-1]
            if n not in self.users:
                return CommandResult(1, "", "no such user")
            if cmd[1] == "-u":
                return CommandResult(0, str(self.users[n]["uid"]))
            return CommandResult(0, " ".join(self.users[n]["groups"]))

        if c == "groupadd":
            gid = (
                int(cmd[cmd.index("-g") + 1])
                if "-g" in cmd else 3000 + len(self.groups)
            )
            self.groups[cmd[-1]] = gid
            return CommandResult(0)

        if c == "useradd":
            name = cmd[-1]
            shell = cmd[cmd.index("-s") + 1]
            comment = cmd[cmd.index("-c") + 1]
            extra = (
                cmd[cmd.index("-G") + 1].split(",")
                if "-G" in cmd else []
            )
            if name in self.groups:  # real Debian useradd: private group already exists -> exit 9
                return CommandResult(9, "", f"useradd: group {name} exists - if you want to add this user to that group, use -g.")
            home = os.path.join(self.home_root, name)
            os.makedirs(home, exist_ok=True)
            self.groups[name] = self.next_uid  # user-private group
            self.users[name] = dict(
                uid=self.next_uid,
                gid=self.next_uid,
                comment=comment,
                home=home,
                shell=shell,
                groups=[name] + extra,
                locked=True,
            )
            self.next_uid += 1
            return CommandResult(0)

        if c == "usermod":
            name = cmd[-1]
            u = self.users[name]
            if "-a" in cmd:
                for g in cmd[cmd.index("-G") + 1].split(","):
                    if g not in u["groups"]:
                        u["groups"].append(g)
            if "-s" in cmd:
                u["shell"] = cmd[cmd.index("-s") + 1]
            if "-c" in cmd:
                u["comment"] = cmd[cmd.index("-c") + 1]
            if "-L" in cmd:
                u["locked"] = True
            if "-U" in cmd:
                u["locked"] = False
            return CommandResult(0)

        if c == "runuser":
            mode = int(cmd[cmd.index("-m") + 1], 8)
            target = cmd[-1]
            os.makedirs(target)
            os.chmod(target, mode)
            u = self.users[cmd[cmd.index("-u") + 1]]
            try:
                os.chown(target, u["uid"], u["gid"])
            except PermissionError:
                pass
            return CommandResult(0)

        return CommandResult(127, "", "unsupported in fake")


def tool_use(name, **arguments):
    """Create one Ollama-format tool call."""
    return {
        "function": {
            "name": name,
            "arguments": arguments,
        }
    }


def text(t):
    """Create one Ollama-format assistant response."""
    return {"message": {"role": "assistant", "content": t}}


class FakeClient:
    """Scripted stand-in for the local Ollama chat API client."""

    def __init__(self, script, format_script=None):
        self.script = list(script)
        self.format_script = None if format_script is None else list(format_script)
        self.requests = []

    def chat(self, **kwargs):
        if "format" in kwargs:   # schema-constrained repair call
            from provisioning_agent.ollama_client import OllamaAPIError
            self.format_requests = getattr(self, "format_requests", []) + [kwargs]
            if not self.format_script:
                raise OllamaAPIError("structured output unsupported (simulated old Ollama)")
            return {"message": {"role": "assistant", "content": self.format_script.pop(0)}}
        self.requests.append(kwargs)
        if not self.script:
            raise AssertionError("FakeClient script is exhausted")
        response = self.script.pop(0)

        # Scripts may supply complete Ollama response dictionaries.
        if isinstance(response, dict):
            if "message" in response:
                return response
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": response.get("tool_calls", []),
                }
            }

        # Or provide ("text", content) / ("tool", name, arguments).
        kind = response[0]
        if kind == "text":
            return text(response[1])
        if kind == "tool":
            return {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [tool_use(response[1], **response[2])],
                }
            }

        raise AssertionError(f"Unsupported FakeClient script entry: {response!r}")
