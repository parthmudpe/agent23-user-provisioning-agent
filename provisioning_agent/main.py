"""Terminal interface for the local Ollama-powered Agent 23."""
import argparse
import os
import sys

from . import config, preflight
from .agent import Agent
from .ollama_client import OllamaClient, OllamaAPIError
from .system_ops import SystemOps
from .tools import Dispatcher

BANNER = """Agent 23 - User Provisioning Agent (Local Ollama)
Type a request in plain English (e.g. "create user alice in group developers").
Commands: /help  /reset  /exit"""


def make_confirm(auto_yes):
    def confirm(cmd, warning):
        if warning:
            print(f"  \033[33m! {warning}\033[0m")
        elif auto_yes:
            print(f"  [auto-approved] {cmd}")
            return True
        try:
            return input(f"  Execute `{cmd}` ? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            return False
    return confirm


SHELL_PREFIXES = ("sudo ", "python3 ", "python ", "./", "cd ", "ls ", "apt ", "ollama ")


def looks_like_shell_command(line):
    """True if the operator typed a terminal command into the agent prompt by mistake."""
    return line.startswith(SHELL_PREFIXES) or line in ("ls", "clear", "exit", "quit")


def print_tool(name, args):
    print(f"  \033[36m> tool: {name} {args}\033[0m")


def build_agent(args):
    audit = os.environ.get("AGENT23_AUDIT_LOG", "logs/agent23_audit.log")
    ops = SystemOps(
        dry_run=args.dry_run,
        confirm=make_confirm(args.yes),
        audit_path=audit,
    )
    model = args.model or os.environ.get("OLLAMA_MODEL", config.DEFAULT_MODEL)
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    agent = Agent(
        OllamaClient(host),
        Dispatcher(ops, on_tool=print_tool),
        model,
    )
    agent.notice = lambda msg: print(f"  \033[33m! {msg}\033[0m")
    return agent


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Agent 23: local Ollama-powered Linux user provisioning"
    )
    ap.add_argument("--dry-run", action="store_true",
                    help="plan only; execute no changes")
    ap.add_argument("--yes", "-y", action="store_true",
                    help="auto-approve normal commands (privileged groups still ask)")
    ap.add_argument("--check", action="store_true",
                    help="only check dependencies and Ollama availability")
    ap.add_argument("--model", help="override the local Ollama model")
    ap.add_argument("--debug", action="store_true",
                    help="print raw model output (also AGENT23_DEBUG=1)")
    ap.add_argument("-c", "--command", help="run one request and exit")
    args = ap.parse_args(argv)

    config.load_env_file()
    result = preflight.check(args.model)
    if args.check or not result["ok"]:
        print(preflight.report(result))
        if not result["ok"]:
            return 1
        return 0 if result.get("ollama_ok", False) else 1

    if not args.dry_run and os.geteuid() != 0:
        print(
            "Not running as root: real system changes will be refused. "
            "Use --dry-run for safe testing.\n"
        )

    agent = build_agent(args)
    if args.debug or os.environ.get("AGENT23_DEBUG") == "1":
        agent.trace = lambda msg: print(f"  \033[90m[debug] {msg}\033[0m")

    if args.command:
        return _one(agent, args.command)

    print(BANNER + (
        "\n[DRY-RUN MODE: no system changes will be executed]"
        if args.dry_run else ""
    ))

    while True:
        try:
            line = input("\nagent23> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not line:
            continue
        if line in ("/exit", "/quit"):
            return 0
        if line == "/reset":
            agent.reset()
            print("Conversation cleared.")
            continue
        if line == "/help":
            print(BANNER)
            continue
        if looks_like_shell_command(line):
            print("That looks like a terminal command. Type /exit first, then run it in the "
                  "Ubuntu shell. Here, type a plain-English request.")
            continue

        _one(agent, line)


def _one(agent, text):
    try:
        print("\n" + agent.ask(text))
        return 0
    except OllamaAPIError as exc:
        agent.reset()
        print(f"Ollama error: {exc}")
        return 2
    except KeyboardInterrupt:
        agent.reset()
        print("\nInterrupted.")
        return 130
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        agent.reset()
        print(f"Agent response error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
