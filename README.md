# Agent 23 - User Provisioning Agent

Terminal AI agent (Python + local Ollama tool calling) that manages Linux users, groups and home
directories from plain English, using only `useradd`, `usermod`, `groupadd`, `mkdir`
(through `runuser`), `id` and `getent`. Never edits `/etc/passwd` or `/etc/group`. No frontend, no C code needed.

## Structure
```
agent23/
├── agent23.py                    launcher
├── requirements.txt  .env.example  .gitignore
├── provisioning_agent/
│   ├── config.py        constants, reserved names, .env loader
│   ├── preflight.py     dependency check + apt install commands
│   ├── validators.py    whitelist validation
│   ├── system_ops.py    command execution, root check, confirm, verify, audit
│   ├── tools.py         tool schemas + dispatcher
│   ├── agent.py         Ollama tool-calling loop
│   └── main.py          CLI
├── tests/               unit tests (simulated system) + real integration test
├── scripts/             install.sh, run_tests.sh
├── docs/                ARCHITECTURE.md (diagram), REPORT.md
└── samples/             sample_session.md, real_integration_output.txt
```

## Install (Ubuntu/Debian)
```bash
cd agent23
./scripts/install.sh        # or manually:
sudo apt update
sudo apt install -y python3 passwd coreutils libc-bin util-linux curl
```
Dependency check only (prints exact install commands for anything missing):
```bash
python3 agent23.py --check
```

## Ollama configuration
```bash
cp .env.example .env && chmod 600 .env
nano .env        # set ANTHROPIC_API_KEY=sk-ant-...  (CLAUDE_MODEL defaults to claude-sonnet-5-5)
```
The `.env` file is read by the program itself, so it works under `sudo`.

## Run
```bash
sudo python3 agent23.py              # interactive, asks y/N before each change
sudo python3 agent23.py --yes        # auto-approve normal commands (privileged groups still ask)
python3 agent23.py --dry-run         # no root needed, nothing executed
sudo python3 agent23.py -c "list all users"
```

## Demo script
1. `create a group called developers`
2. `create user alice with full name Alice Smith in group developers`
3. `create folder projects/web for alice with mode 750`
4. `show me alice` / `lock alice` / `change alice's shell to /bin/sh`
5. `add alice to sudo` (shows privileged warning; answer `n`)
6. `create folder ../../etc/x for alice` (rejected by validation)
7. Verify independently: `id alice`, `getent passwd alice`, `ls -ld /home/alice/projects/web`, `tail logs/agent23_audit.log`

Cleanup after the demo (manual, not an agent feature): `sudo userdel -r alice; sudo groupdel developers`.

## Tests
```bash
./scripts/run_tests.sh                       # 76 unit tests, no root/API needed
sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_real          # real commands; disposable machine only
sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_agent_real    # reported 'agenttest' scenario on the real system
```
Status recorded at build time: unit tests and integration test were executed and passed in a
Debian-based root sandbox. The loop is covered by a scripted fake Ollama client; sample
transcript in `samples/sample_session.md` is illustrative.

## Small-model guardrails (llama3.2:3b)
- `create_user` always makes `/home/<username>`; invented `groups` are ignored unless the request named them
  (e.g. "in group qa"), and the username is never used as a supplementary group.
- Invented arguments (`password`, `uid`, `home_directory`...) are dropped and reported; custom home paths are refused.
- A malformed/unknown tool-call JSON reply gets feedback and up to 2 retries before the turn stops with
  "Unsupported tool-call format. No action was taken."
- If the model's reply is unusable (or it answers without calling a tool), one schema-constrained
  repair call (Ollama structured outputs, tool name restricted to the 8 tools) is made; the result
  still passes sanitising, validation, confirmation and dry-run like any other call.
- `python3 agent23.py --debug` (or `AGENT23_DEBUG=1`) prints the raw model output.
- All validation, root check, y/N confirmation and `--dry-run` behaviour are unchanged.
- If a 3B model still misreads requests, try `OLLAMA_MODEL=qwen2.5:7b` or `llama3.1:8b`.

## Safety model
Validation whitelists, argv-only subprocess (`shell=False`), root check, per-command operator
approval, protected system accounts (uid < 1000), privileged-group warnings, symlink/home checks,
audit log, and post-change verification with `id`/`getent`/`stat`. See `docs/ARCHITECTURE.md` and `docs/REPORT.md`.

## Troubleshooting
- `Root privileges required`: run with `sudo` or use `--dry-run`.
- `local Ollama API MISSING`: start Ollama (`ollama serve`) or fix `OLLAMA_HOST` in `.env`.
- `model MISSING`: `ollama pull <model>` for the model in `OLLAMA_MODEL`.
