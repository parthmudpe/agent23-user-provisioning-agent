"""Claude tool schemas and the dispatcher that maps tool calls to SystemOps."""
from .system_ops import OpError, SystemOps, UserDeclined
from .validators import ValidationError

TOOLS = [
    {"name": "get_user_info",
     "description": "Look up a user (getent passwd + id): uid, gid, home, shell, groups, whether home exists.",
     "input_schema": {"type": "object", "properties": {"username": {"type": "string"}},
                      "required": ["username"]}},
    {"name": "get_group_info",
     "description": "Look up a group (getent group): gid and members.",
     "input_schema": {"type": "object", "properties": {"groupname": {"type": "string"}},
                      "required": ["groupname"]}},
    {"name": "list_users",
     "description": "List regular (non-system) user accounts, uid 1000-60000.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "create_group",
     "description": "Create a new group with groupadd. Optional gid (1000-60000).",
     "input_schema": {"type": "object", "properties": {
         "groupname": {"type": "string"}, "gid": {"type": "integer"}},
         "required": ["groupname"]}},
    {"name": "create_user",
     "description": "Create a user with a home directory (useradd -m). Groups must already exist. "
                    "ALWAYS creates /home/<username>. Shell defaults to /bin/bash. No password is set. "
                    "Pass groups/shell/comment ONLY if the user asked; never put the username in groups.",
     "input_schema": {"type": "object", "properties": {
         "username": {"type": "string"},
         "groups": {"type": "array", "items": {"type": "string"}, "description": "Supplementary groups"},
         "shell": {"type": "string"}, "comment": {"type": "string", "description": "Full name"}},
         "required": ["username"]}},
    {"name": "add_user_to_groups",
     "description": "Append an existing user to supplementary groups (usermod -a -G).",
     "input_schema": {"type": "object", "properties": {
         "username": {"type": "string"},
         "groups": {"type": "array", "items": {"type": "string"}}},
         "required": ["username", "groups"]}},
    {"name": "modify_user",
     "description": "Change an existing user's login shell, full name (comment), or lock/unlock the account.",
     "input_schema": {"type": "object", "properties": {
         "username": {"type": "string"}, "shell": {"type": "string"},
         "comment": {"type": "string"}, "lock": {"type": "boolean", "description": "true=lock, false=unlock"}},
         "required": ["username"]}},
    {"name": "create_directory",
     "description": "Create a directory inside a user's home, owned by that user (mkdir via runuser). "
                    "relative_path is relative to the home. mode defaults to 700. "
                    "NOT for creating the home directory itself (create_user does that).",
     "input_schema": {"type": "object", "properties": {
         "username": {"type": "string"}, "relative_path": {"type": "string"},
         "mode": {"type": "string", "description": "octal, e.g. 700 or 750"}},
         "required": ["username", "relative_path"]}},
]


class Dispatcher:
    def __init__(self, ops: SystemOps, on_tool=None):
        self.ops = ops
        self.on_tool = on_tool
        self._map = {
            "get_user_info": lambda a: self._wrap("user", self._user_info(a.get("username"))),
            "get_group_info": lambda a: self._wrap("group", self.ops.get_group(a.get("groupname"))),
            "list_users": lambda a: {"users": self.ops.list_users()},
            "create_group": lambda a: self.ops.create_group(a.get("groupname"), a.get("gid")),
            "create_user": lambda a: self.ops.create_user(
                a.get("username"), a.get("groups"), a.get("shell"), a.get("comment", "")),
            "add_user_to_groups": lambda a: self.ops.add_user_to_groups(a.get("username"), a.get("groups")),
            "modify_user": lambda a: self.ops.modify_user(
                a.get("username"), a.get("shell"), a.get("comment"), a.get("lock")),
            "create_directory": lambda a: self.ops.create_directory(
                a.get("username"), a.get("relative_path"), a.get("mode", "700")),
        }

    def _user_info(self, username):
        user = self.ops.get_user(username)
        if user:
            user["locked"] = self.ops.is_locked(user["username"])  # None when not root
        return user

    @staticmethod
    def _wrap(key, value):
        return {"found": value is not None, key: value}

    def execute(self, name, args):
        """Return (result_dict, is_error)."""
        if self.on_tool:
            self.on_tool(name, args)
        fn = self._map.get(name)
        if fn is None:
            return {"error": f"Unknown tool '{name}'."}, True
        if not isinstance(args, dict):
            return {"error": "Tool input must be an object."}, True
        try:
            return fn(args), False
        except ValidationError as e:
            return {"error": f"Validation failed: {e}"}, True
        except UserDeclined as e:
            return {"error": str(e), "declined": True}, True
        except OpError as e:
            return {"error": str(e)}, True
        except Exception as e:  # last-resort guard; never crash the agent loop
            return {"error": f"Unexpected {type(e).__name__}: {e}"}, True
