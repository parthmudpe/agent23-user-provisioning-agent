
"""Ollama tool-calling loop for Agent 23."""
import ast
import json
import re

from . import config
from .ollama_client import OllamaAPIError
from .system_ops import OpError
from .tools import TOOLS, Dispatcher
from .validators import (ValidationError, validate_comment, validate_group_list,
                         validate_shell, validate_username)

_MUTATION_TOOLS = frozenset({"create_user", "create_group", "add_user_to_groups",
                             "modify_user", "create_directory"})


_NUDGE = ("You answered without calling a tool. Never guess whether users, groups or "
          "folders exist. Call the right tool now (get_user_info, get_group_info, create_user, "
          "...) using a real tool call, or ask one short clarifying question.")


_READ_TOOLS = frozenset({"get_user_info", "get_group_info", "list_users"})


def _format_read(name, res):
    if name == "get_user_info":
        if not res.get("found"):
            return "No such user."
        u = res["user"]
        locked = {True: "yes", False: "no"}.get(u.get("locked"), "unknown")
        return (f"User {u['username']}: uid {u['uid']}, gid {u['gid']}, home {u['home']} "
                f"({'exists' if u.get('home_exists') else 'missing'}), shell {u['shell']}, "
                f"groups: {', '.join(u.get('groups', [])) or '-'}, locked: {locked}"
                + (f", comment: {u['comment']}" if u.get("comment") else ""))
    if name == "get_group_info":
        if not res.get("found"):
            return "No such group."
        g = res["group"]
        return f"Group {g['group']}: gid {g['gid']}, members: {', '.join(g['members']) or '-'}"
    users = res.get("users", [])
    return "Users:\n" + "\n".join(f"  {u['username']} (uid {u['uid']}, home {u['home']})"
                                   for u in users) if users else "No regular users."


def _call_name(call):
    fn = call.get("function") if isinstance(call, dict) else None
    return fn.get("name", "") if isinstance(fn, dict) else ""


SYSTEM_PROMPT = """You are Agent 23, a Linux user-provisioning assistant.
Use ONLY the supplied tools for Linux user, group, and directory operations.

IMPORTANT TOOL RULES:
- Use actual tool_calls, never pretend tool calls in text.
- Match tool arguments to their JSON schema.
- Inspect users and groups when their state is unknown.
- Create missing supplementary groups before creating a user.
- Never bypass validation or authorization.
- Never edit /etc/passwd or /etc/group, set passwords, delete users,
  or modify system accounts.
- Privileged groups require explicit human approval through the system.
- Report success only when the tool result says verified=true.
- If dry_run=true, describe the operation as simulated, not executed.
- If a request is ambiguous, ask one short clarifying question.
- create_user ALWAYS creates /home/<username>; there is no separate home-directory tool.
  Do not use create_directory for the home directory.
- Pass groups, shell or comment to create_user ONLY if the user explicitly asked for them.
  Never put the username itself in groups (a private group is created automatically).
- Never invent tool names or arguments (no password, uid, home_directory, ...).
- Example: "create user bob" -> call create_user with {"username": "bob"} and nothing else.
- Be concise and truthful."""


def ollama_tool_schemas():
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in TOOLS
    ]


def _known_tool_names():
    return {tool["name"] for tool in TOOLS}


def _coerce_args(value):
    """Arguments may arrive as a dict or as a JSON / Python-literal string."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return None
    return value if isinstance(value, dict) else None


def _extract_tool_call(data):
    """Understand {name|tool, arguments|parameters|input} and the OpenAI-style
    {"type": "function", "function": {...}} wrapper. Known tools only."""
    if not isinstance(data, dict):
        return None
    inner = data.get("function")
    src = inner if isinstance(inner, dict) else data
    name = src.get("name") or src.get("tool") or (inner if isinstance(inner, str) else None)
    raw = src.get("arguments", src.get("parameters", src.get("input")))
    args = {} if raw is None else _coerce_args(raw)
    name = _TOOL_ALIASES.get(name, name)
    if name in _known_tool_names() and args is not None:
        return {"function": {"name": name, "arguments": args}}
    return None


def _decoded_objects(content):
    decoder = json.JSONDecoder()
    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            data, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data


def _json_tool_fallback(content):
    """Accept structured calls to known tools, never plain prose."""
    if not isinstance(content, str):
        return None
    for data in _decoded_objects(content):
        call = _extract_tool_call(data)
        if call:
            return [call]
    return None


_TOOL_ALIASES = {"get_user": "get_user_info", "user_info": "get_user_info",
                 "get_group": "get_group_info", "group_info": "get_group_info",
                 "add_user_to_group": "add_user_to_groups", "add_to_group": "add_user_to_groups",
                 "add_to_groups": "add_user_to_groups"}

_NAME_KEYS = {"name", "tool", "function"}
_ARG_KEYS = {"parameters", "arguments", "input"}


def _looks_like_tool_json(content):
    """True if the reply contains JSON shaped like a tool call (valid or not)."""
    if not isinstance(content, str):
        return False
    for d in _decoded_objects(content):
        keys = set(d)
        if (_NAME_KEYS & keys and _ARG_KEYS & keys) or isinstance(d.get("function"), dict):
            return True
    return False


def _normalize_arguments(name, arguments):
    """Normalize common local-model mistakes; validators remain authoritative."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            try:
                arguments = ast.literal_eval(arguments)
            except (ValueError, SyntaxError):
                return None

    if not isinstance(arguments, dict):
        return None

    if name == "create_group":
        if not arguments.get("groupname"):
            for alias in ("group_name", "group", "name"):
                if arguments.get(alias):
                    arguments["groupname"] = arguments.pop(alias)
                    break

        if not arguments.get("groupname") and arguments.get("groups"):
            groups = arguments.pop("groups")

            if isinstance(groups, str):
                try:
                    groups = json.loads(groups)
                except json.JSONDecodeError:
                    try:
                        groups = ast.literal_eval(groups)
                    except (ValueError, SyntaxError):
                        pass

            if isinstance(groups, list) and len(groups) == 1:
                if isinstance(groups[0], str):
                    arguments["groupname"] = groups[0]
            elif isinstance(groups, str):
                arguments["groupname"] = groups

        arguments.pop("groups", None)

    if name == "create_user":
        for alias, target in (("user", "username"), ("user_name", "username"),
                              ("name", "username"), ("login", "username"),
                              ("full_name", "comment"), ("fullname", "comment"),
                              ("gecos", "comment"), ("group", "groups"),
                              ("group_name", "groups")):
            if alias in arguments and not arguments.get(target):
                value = arguments.pop(alias)
                arguments[target] = [value] if target == "groups" and isinstance(value, str) else value

    schema = next(
        (
            tool["input_schema"]
            for tool in TOOLS
            if tool["name"] == name
        ),
        None,
    )

    if schema is None:
        return arguments

    for key, spec in schema.get("properties", {}).items():
        if key not in arguments:
            continue

        expected = spec.get("type")
        value = arguments[key]

        if expected == "array" and isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    continue

            if isinstance(parsed, list):
                arguments[key] = parsed

        elif expected == "boolean" and isinstance(value, str):
            low = value.strip().lower()
            if low in ("true", "yes", "1"):
                arguments[key] = True
            elif low in ("false", "no", "0"):
                arguments[key] = False

        elif expected == "integer" and isinstance(value, str):
            try:
                arguments[key] = int(value)
            except ValueError:
                pass

    return arguments


_HOME_KEYS = ("home", "home_dir", "home_directory", "homedir", "create_home",
              "create_home_dir", "create_home_directory", "m")


def _truthy(value):
    return value is True or (isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"))


def _strip_unknown_args(name, arguments):
    """Drop arguments the tool does not define. Returns (error|None, ignored_names)."""
    schema = next((t["input_schema"] for t in TOOLS if t["name"] == name), {})
    props = set(schema.get("properties", {}))
    if name == "create_user":
        username = arguments.get("username")
        for key in _HOME_KEYS:
            if key not in arguments:
                continue
            value = arguments.pop(key)
            default_home = isinstance(username, str) and isinstance(value, str) \
                and value.rstrip("/") == f"/home/{username}"
            if value in (None, "") or _truthy(value) or default_home:
                continue
            return ("Custom or disabled home directories are not supported: create_user "
                    "always creates /home/<username>."), []
    ignored = [k for k in list(arguments) if k not in props]
    for key in ignored:
        arguments.pop(key)
    return None, ignored


class Agent:
    def __init__(
        self,
        client,
        dispatcher: Dispatcher,
        model=config.DEFAULT_MODEL,
    ):
        self.client = client
        self.dispatcher = dispatcher
        self.model = model
        self.messages = []
        self._requests = []        # raw user requests (used to detect invented groups)
        self.notice = lambda msg: None
        self.trace = lambda msg: None   # set by --debug

    def reset(self):
        self.messages = []
        self._requests = []

    def _constrained_call(self):
        """One schema-constrained chat call (Ollama structured outputs).
        Returns ("call", call_dict) | ("reply", text) | None if unavailable/unusable."""
        names = sorted(_known_tool_names())
        schema = {
            "type": "object",
            "properties": {"tool": {"type": "string", "enum": names + ["reply"]},
                           "arguments": {"type": "object"}},
            "required": ["tool", "arguments"],
        }
        guide = "; ".join(
            f"{t['name']}({', '.join(t['input_schema'].get('properties', {}))})" for t in TOOLS)
        system = (SYSTEM_PROMPT + "\n\nRespond with ONLY JSON: "
                  '{"tool": <name>, "arguments": {...}}. Tools and argument names: ' + guide
                  + '. Use tool "reply" with {"message": "..."} only for a question, '
                  "clarification or small talk. Choose the tool for the user's latest request.")
        try:
            resp = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, *self.messages[:-1]],
                format=schema, stream=False,
                options={"temperature": 0, "num_ctx": 8192})
            raw = (resp.get("message") or {}).get("content", "")
            self.trace(f"constrained content={raw!r}")
            data = json.loads(raw)
        except (OllamaAPIError, json.JSONDecodeError, AttributeError, TypeError):
            return None
        if not isinstance(data, dict):
            return None
        tool = data.get("tool")
        args = _coerce_args(data.get("arguments", {})) or {}
        if tool == "reply":
            msg = args.get("message")
            return ("reply", msg) if isinstance(msg, str) and msg.strip() else None
        if tool in _known_tool_names():
            return ("call", {"function": {"name": tool, "arguments": args}})
        return None

    def _sanitize_group_args(self, name, arguments):
        """Small models invent 'groups'. Keep only groups the user actually named, and never
        the username itself on create_user (useradd already makes that private group)."""
        if name not in ("create_user", "add_user_to_groups"):
            return []
        groups = arguments.get("groups")
        if not isinstance(groups, list):
            return []
        corpus = "\n".join(self._requests)
        username = arguments.get("username")
        keep, ignored = [], []
        for g in groups:
            if not isinstance(g, str):
                keep.append(g)           # validators will reject it with a clear error
                continue
            named = re.search(
                rf"(?<![\w-])(?:groups?|members?\s+of|belong(?:s)?\s+to|into|in|to)\s+"
                rf"(?:(?:the|a)\s+)?(?:groups?\s+)?(?:[\w-]+\s*(?:,|and)\s*)*"
                rf"{re.escape(g)}(?![\w-])", corpus, re.I)
            if (name == "create_user" and g == username) or not named:
                ignored.append(g)
            else:
                keep.append(g)
        if ignored:
            if keep or name == "add_user_to_groups":
                arguments["groups"] = keep
            else:
                arguments.pop("groups", None)
        return ignored

    def _precheck_create_user(self, arguments):
        """Validate before any supplementary group is auto-created (no orphan groups)."""
        ops = self.dispatcher.ops
        try:
            username = validate_username(arguments.get("username"))
            validate_group_list(arguments.get("groups"))
            validate_comment(arguments.get("comment") or "")
            validate_shell(arguments.get("shell") or config.DEFAULT_SHELL, ops.allowed_shells())
            if username in config.RESERVED_USERS:
                return f"Username '{username}' is reserved."
            if ops.get_user(username):
                return f"User '{username}' already exists."
        except (ValidationError, OpError) as exc:
            return f"Validation failed: {exc}"
        return None

    def _direct_read(self, request):
        """Handle obvious read-only requests deterministically, without LLM tool choice."""
        text = request.strip()
        patterns = (
            (r"(?:show|display|inspect|look up|get|find)\s+(?:me\s+)?(?:the\s+)?(?:details?\s+(?:for|of)\s+)?(?:user\s+)?([a-z_][a-z0-9_.-]*)", "user"),
            (r"(?:user\s+)?(?:info|information|details?)\s+(?:for|of|about)\s+(?:user\s+)?([a-z_][a-z0-9_.-]*)", "user"),
            (r"(?:show|display|inspect|look up|get|find)\s+(?:me\s+)?(?:the\s+)?group\s+([a-z_][a-z0-9_.-]*)", "group"),
        )
        lowered = text.lower().strip().rstrip("?.!")
        if re.fullmatch(r"(?:list|show|display)\s+(?:all\s+)?users", lowered):
            name, args = "list_users", {}
        else:
            match = None
            kind = None
            for pattern, candidate_kind in patterns:
                match = re.fullmatch(pattern, lowered, re.I)
                if match:
                    kind = candidate_kind
                    break
            if not match:
                return None
            target = match.group(1)
            if kind == "group":
                name, args = "get_group_info", {"groupname": target}
            else:
                # Avoid interpreting common imperative requests as lookups.
                if target in {"a", "an", "new", "user", "group", "me", "all"}:
                    return None
                name, args = "get_user_info", {"username": target}

        result, is_error = self.dispatcher.execute(name, args)
        if is_error:
            return "Could not complete lookup: " + str(result.get("error", "unknown error"))
        return _format_read(name, result)

    def ask(self, text):
        direct = self._direct_read(text)
        if direct is not None:
            self.messages.append({"role": "user", "content": text})
            self.messages.append({"role": "assistant", "content": direct})
            self._requests.append(text)
            return direct
        self.messages.append({"role": "user", "content": text})
        self._requests.append(text)
        bad_formats = 0
        nudged = False
        repaired = False
        last_error = None      # last real tool error (for a clear final message)
        last_ok = None         # command of the last verified mutation
        last_read = None       # (tool, result) of the last successful lookup

        # Track exact calls and successful mutations separately.
        seen_calls = set()
        successful_mutations = set()
        tools_ran = False
        dry_plans = []

        for _ in range(config.MAX_AGENT_STEPS):
            response = self.client.chat(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    *self.messages,
                ],
                tools=ollama_tool_schemas(),
                stream=False,
                options={"temperature": 0, "num_ctx": 8192},
            )

            message = response.get("message", {})
            if not isinstance(message, dict):
                return "Error: Ollama returned an invalid message."

            content = message.get("content", "") or ""
            calls = message.get("tool_calls") or []
            self.trace(f"model content={content!r} tool_calls={calls!r}")

            if not calls:
                calls = _json_tool_fallback(content) or []
                if calls:
                    content = ""

            assistant_message = {
                "role": "assistant",
                "content": content,
            }

            if calls:
                assistant_message["tool_calls"] = calls

            self.messages.append(assistant_message)

            if not calls:
                unusable = _looks_like_tool_json(content)
                reply = content.strip()
                toolless = not tools_ran and not reply.endswith("?")

                # Step 1: ask Ollama for schema-constrained JSON (guaranteed parseable,
                # tool name restricted to our tools). Skipped silently if unsupported.
                if (unusable or toolless) and not repaired:
                    repaired = True
                    forced = self._constrained_call()
                    if forced and forced[0] == "call":
                        calls = [forced[1]]
                        assistant_message["content"] = ""
                        assistant_message["tool_calls"] = calls
                    elif forced and forced[0] == "reply":
                        content = reply = forced[1].strip()
                        assistant_message["content"] = content
                        unusable = False
                        toolless = not tools_ran and not reply.endswith("?")

            if not calls:
                # Step 2: classic feedback retries (older Ollama / repair unavailable).
                if unusable:
                    bad_formats += 1
                    if bad_formats > 2:
                        return ("Unsupported tool-call format. No action was taken. "
                                "Last model output: " + content.strip()[:200]
                                + "  (rerun with --debug to see raw output)")
                    self.messages.append({
                        "role": "user",
                        "content": (
                            "Your last reply was not a valid tool call, so nothing was "
                            "executed. Valid tools: " + ", ".join(sorted(_known_tool_names()))
                            + ". Use a real tool call with those exact names, or answer in "
                            "plain text. create_user already creates /home/<username>."),
                    })
                    continue

                if toolless:
                    if not nudged:
                        nudged = True
                        self.messages.append({"role": "user", "content": _NUDGE})
                        continue
                    reply = ("[Warning: no tool was run this turn, so nothing was changed "
                             "and the text below is unverified.]\n" + reply)
                return reply

            priority = {
                "create_group": 0,
                "create_user": 1,
                "add_user_to_groups": 2,
                "modify_user": 2,
                "create_directory": 3,
            }

            calls.sort(key=lambda call: priority.get(_call_name(call), 1))

            repeat_blocked = False
            step_lock = {}
            for call in calls:
                if not _call_name(call) and not (
                        isinstance(call, dict) and isinstance(call.get("function"), dict)):
                    self.messages.append({
                        "role": "tool", "name": "unknown", "tool_name": "unknown",
                        "content": json.dumps({"result": {"error": "Malformed tool call."},
                                               "is_error": True}),
                    })
                    continue
                tools_ran = True
                function = call["function"]
                name = function.get("name", "")
                name = _TOOL_ALIASES.get(name, name) if isinstance(name, str) else ""
                arguments = _normalize_arguments(
                    name,
                    function.get("arguments", {}),
                )

                result = None
                is_error = False
                mutation_key = None
                arg_error, ignored_args, ignored_groups = None, [], []
                blocked_now = False
                if isinstance(arguments, dict) and name in _known_tool_names():
                    arg_error, ignored_args = _strip_unknown_args(name, arguments)
                    ignored_groups = self._sanitize_group_args(name, arguments)
                    if (name == "modify_user" and not arg_error
                            and isinstance(arguments.get("lock"), bool)):
                        who = arguments.get("username")
                        if step_lock.get(who, arguments["lock"]) != arguments["lock"]:
                            arg_error = ("Conflicting lock and unlock requests for the same user "
                                         "in one step; only the first was applied.")
                        else:
                            step_lock[who] = arguments["lock"]

                if name not in _known_tool_names():
                    result = {"error": f"Unknown tool: {name}"}
                    is_error = True

                elif arguments is None:
                    result = {
                        "error": (
                            "Tool arguments must be a valid JSON object."
                        )
                    }
                    is_error = True

                elif arg_error:
                    result = {"error": arg_error}
                    is_error = True

                else:
                    call_key = json.dumps(
                        {"name": name, "arguments": arguments},
                        sort_keys=True,
                        default=str,
                    )

                    mutation_tools = {
                        "create_user",
                        "create_group",
                        "add_user_to_groups",
                        "modify_user",
                        "create_directory",
                    }

                    target = (
                        arguments.get("username")
                        or arguments.get("groupname")
                        or arguments.get("relative_path")
                        or arguments.get("directory")
                    )

                    # Only user/group creation is keyed by target; other mutations
                    # (several folders, shell then lock, ...) are legitimately repeated.
                    if name in ("create_user", "create_group"):
                        mutation_key = (name, target)
                    else:
                        mutation_key = (name, call_key)

                    if call_key in seen_calls:
                        blocked_now = True
                        result = {
                            "error": (
                                "Repeated identical tool call blocked. "
                                "Do not retry the same arguments."
                            )
                        }
                        is_error = True

                    elif (
                        name in mutation_tools
                        and mutation_key in successful_mutations
                    ):
                        blocked_now = True
                        result = {
                            "error": (
                                "This mutation already succeeded for "
                                "the requested target."
                            )
                        }
                        is_error = True

                    else:
                        # Record only once. A failed call may be retried
                        # with corrected arguments, but identical calls
                        # are blocked to avoid loops.
                        seen_calls.add(call_key)

                        # Check/create supplementary groups before useradd.
                        if name == "create_user":
                            group_error = None
                            groups = arguments.get("groups") or []

                            precheck = self._precheck_create_user(arguments)
                            if precheck:
                                result = {"error": precheck}
                                is_error = True
                            elif not isinstance(groups, list):
                                result = {
                                    "error": (
                                        "The groups argument must be a "
                                        "JSON array of group names."
                                    )
                                }
                                is_error = True
                            else:
                                for group in groups:
                                    lookup, lookup_error = (
                                        self.dispatcher.execute(
                                            "get_group_info",
                                            {"groupname": group},
                                        )
                                    )

                                    if lookup_error:
                                        group_error = {
                                            "error": (
                                                f"Could not check group "
                                                f"'{group}': {lookup}"
                                            )
                                        }
                                        break

                                    if lookup.get("found"):
                                        continue

                                    created, create_error = (
                                        self.dispatcher.execute(
                                            "create_group",
                                            {"groupname": group},
                                        )
                                    )

                                    if create_error:
                                        group_error = {
                                            "error": (
                                                f"Could not create group "
                                                f"'{group}': {created}"
                                            )
                                        }
                                        break

                                    if created.get("dry_run"):
                                        group_error = {
                                            "error": (
                                                f"Dry run only: group "
                                                f"'{group}' was not created. "
                                                "User creation was not "
                                                "attempted."
                                            )
                                        }
                                        break

                                    if created.get("verified") is not True:
                                        group_error = {
                                            "error": (
                                                f"Group '{group}' was not "
                                                "verified after creation."
                                            )
                                        }
                                        break

                                if group_error is not None:
                                    result = group_error
                                    is_error = True

                                elif not is_error:
                                    result, is_error = (
                                        self.dispatcher.execute(
                                            name, arguments
                                        )
                                    )

                        else:
                            result, is_error = self.dispatcher.execute(
                                name, arguments
                            )

                        # Remember a mutation only after verified success.
                        if (
                            name in mutation_tools
                            and not is_error
                            and isinstance(result, dict)
                            and result.get("verified") is True
                        ):
                            successful_mutations.add(mutation_key)

                if isinstance(result, dict):
                    if is_error and not blocked_now:
                        last_error = result.get("error") or last_error
                    elif result.get("verified") is True:
                        last_ok = result.get("command") or last_ok
                    elif name in _READ_TOOLS and not is_error:
                        last_read = (name, result)
                if blocked_now:
                    repeat_blocked = True

                if isinstance(result, dict) and (ignored_args or ignored_groups):
                    if ignored_args:
                        result["ignored_arguments"] = ignored_args
                    if ignored_groups:
                        result["ignored_groups"] = ignored_groups
                    result["note"] = "Arguments/groups the user did not request were ignored."
                    self.notice("ignored unrequested input: "
                                + ", ".join(ignored_args + ignored_groups))

                self.messages.append({
                    "role": "tool",
                    "name": name or "unknown",
                    "tool_name": name or "unknown",
                    "content": json.dumps({
                        "result": result,
                        "is_error": is_error,
                    }),
                })

                if isinstance(result, dict) and result.get("dry_run") is True:
                    dry_plans.append(result.get("planned", "not available"))

            if repeat_blocked and not dry_plans:
                if last_error and not last_ok:
                    return ("Could not complete the request: " + str(last_error)
                            + " No further action was taken.")
                if last_ok:
                    return "Done. Verified: " + str(last_ok)
                if last_read:
                    return _format_read(*last_read)
                return "Stopped: the model kept repeating the same call. No further action was taken."

            if dry_plans:
                return ("DRY RUN: nothing was executed. Planned commands:\n"
                        + "\n".join(f"  {p}" for p in dry_plans))

        return (
            "Stopped safely: step limit reached. The model exceeded "
            "the tool-call limit; no further operations were run."
            + (f" Last error: {last_error}" if last_error else "")
        )
