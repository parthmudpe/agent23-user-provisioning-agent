# Agent 23 — User Provisioning Agent

A terminal-based AI agent that simplifies Linux user and group administration through natural-language commands. Built using Python and local Ollama, Agent 23 translates user requests into validated system operations with safety checks, confirmation prompts, and dry-run support.

## Overview

Managing Linux users and groups often requires administrators to remember commands, options, and permission requirements. Agent 23 provides a simpler interface by allowing administrators to express supported operations in plain English.

The agent interprets the request, selects an appropriate tool, validates its arguments, and executes the operation through a controlled system-operations layer. It is designed to avoid directly editing `/etc/passwd` or `/etc/group`.

## Features

- **Natural-language interaction:** Perform supported administration tasks using plain English.
- **User management:** Create users, retrieve account information, and perform supported account modifications.
- **Group management:** Create groups, inspect group information, and manage supported group memberships.
- **Directory management:** Create supported directories with validated ownership and permissions.
- **Dry-run mode:** Preview planned operations without making system changes.
- **Input validation:** Validate usernames, group names, paths, and command arguments.
- **Confirmation prompts:** Review and approve operations before execution.
- **Privilege checks:** Require appropriate permissions for real system modifications.
- **Audit logging:** Maintain records of operations where supported.
- **Post-operation verification:** Check system state after supported operations.
- **Local AI integration:** Use Ollama to interpret requests and generate tool calls.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python 3 | Application logic and command-line interface |
| Ollama | Local language-model inference and tool calling |
| Linux utilities | User, group, and directory administration |
| Bash | Installation and test scripts |
| Python unittest | Automated testing |

## System Architecture

```text
        User Request
             |
             v
     Command-Line Interface
             |
             v
       AI Agent + Ollama
             |
             v
      Tool-Call Processing
             |
             v
      Input Validation
             |
             v
      System Operations
             |
             v
     Linux System Utilities
             |
             v
    Verification and Logging
             |
             v
        Final Response
```

The AI agent interprets the request, while the validation and system-operations layers control how the request is handled. Real system changes remain subject to the application's permission checks and confirmation mechanisms.

## Project Structure

```text
agent23-user-provisioning-agent/
├── agent23.py
├── requirements.txt
├── .env.example
├── provisioning_agent/
│   ├── config.py
│   ├── preflight.py
│   ├── validators.py
│   ├── system_ops.py
│   ├── tools.py
│   ├── agent.py
│   └── main.py
├── tests/
├── scripts/
│   ├── install.sh
│   └── run_tests.sh
├── docs/
│   ├── ARCHITECTURE.md
│   └── REPORT.md
└── samples/
```

## Requirements

- Ubuntu or a supported Debian-based Linux environment
- Python 3
- Ollama installed and running
- A compatible language model available in Ollama
- Appropriate privileges for system administration operations

The project can be developed and tested in a virtual machine or WSL environment. Real-system integration tests should be performed on a disposable test environment.

## Installation

Clone the repository:

```bash
git clone https://github.com/parthmudpe/agent23-user-provisioning-agent.git
cd agent23-user-provisioning-agent
```

Install the required system utilities:

```bash
sudo apt update
sudo apt install -y python3 passwd coreutils libc-bin util-linux curl
```

Run the installation script:

```bash
chmod +x scripts/install.sh scripts/run_tests.sh
./scripts/install.sh
```

Check the environment and dependencies:

```bash
python3 agent23.py --check
```

Follow any installation or configuration instructions reported by the checker.

## Ollama Configuration

1. Install Ollama using the official instructions at https://ollama.com/.
2. Start the Ollama service.
3. Download a language model supported by the project.
4. Check `.env.example` and `provisioning_agent/config.py` for the supported model and host configuration.
5. Ensure the configured model is available before starting the agent.

If the project requires a `.env` file, create it using the provided example:

```bash
cp .env.example .env
chmod 600 .env
```

Configure only variables supported by the current implementation. Do not commit credentials or secrets to the repository.

## Running the Agent

### Check dependencies

```bash
python3 agent23.py --check
```

### Start in dry-run mode

```bash
python3 agent23.py --dry-run
```

Dry-run mode is useful for checking how a request is interpreted and reviewing planned operations without applying them.

### Start the interactive agent

```bash
sudo python3 -B agent23.py
```

Review each proposed system change and approve it only when it matches your intention.

### Execute a single request

```bash
sudo python3 -B agent23.py -c "list all users"
```

### Automatic approval mode

```bash
sudo python3 -B agent23.py --yes
```

Use automatic approval only in a controlled environment. Review the implementation's confirmation rules before enabling it.

## Example Requests

| Natural-language request | Intended operation |
|---|---|
| `list all users` | Display user accounts |
| `show user demo1` | Retrieve account information |
| `create a group called developers` | Create a group |
| `create user alice` | Create a user |
| `add alice to group developers` | Add a user to a group |
| `lock user alice` | Request a supported account-lock operation |
| `change alice's shell to /bin/sh` | Change a user's login shell, if supported |

Exact behavior depends on the tools implemented in the current version. Always review the planned operation before approving a real system change.

## Safety and Security

Agent 23 incorporates safeguards intended to reduce the risk of unintended system modifications:

- **Input validation:** Validates supported names, paths, and arguments.
- **Controlled command execution:** Uses argument-based subprocess execution rather than shell command construction.
- **Privilege enforcement:** Checks whether sufficient permissions are available.
- **Confirmation prompts:** Allows the operator to review changes before execution.
- **Dry-run mode:** Supports safe previews without applying changes.
- **Account and group safeguards:** Applies restrictions to sensitive system accounts and privileged operations where implemented.
- **Audit logging:** Records operations where supported.
- **Verification:** Checks the resulting system state where supported.

These safeguards do not eliminate all risks. Use least privilege, review commands and logs, and test changes on a disposable Linux environment before using the agent on an important system.

## Testing

Run the automated test suite:

```bash
./scripts/run_tests.sh
```

The repository includes unit tests and real-system integration tests. Run unit tests first.

Real-system integration tests may create or modify Linux accounts and groups. Run them only in a disposable test environment and review the test code before execution.

Example integration commands, if supported by the current checkout:

```bash
sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_real
sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_agent_real
```

Record the actual results from the current version rather than relying on earlier test runs.

## Troubleshooting

**Root privileges required**

Use dry-run mode to preview operations or run real administrative operations with appropriate privileges.

**Ollama API unavailable**

Check that Ollama is installed, running, and reachable at the configured host.

**Model unavailable**

Download a compatible model and verify its name in the project configuration.

**Request interpreted incorrectly**

Try a more explicit request and review the proposed tool call and arguments. Never approve an operation that does not match your intention.

**No changes after a dry run**

This is expected. Dry-run mode previews operations rather than applying them.

## Limitations

- The agent can only perform operations exposed by its implemented tools.
- Natural-language interpretation can be imperfect, particularly with ambiguous requests or smaller models.
- Real system modifications require appropriate Linux permissions.
- Integration tests must be isolated from important system accounts and configuration.

## Future Enhancements

- Improve intent recognition for ambiguous requests.
- Expand regression testing for user and group management.
- Improve group-listing and group-membership workflows.
- Provide clearer error messages and structured operation results.
- Add verified terminal screenshots and demonstration output.
- Introduce continuous integration for automated testing.

## Documentation

- [Architecture Documentation](docs/ARCHITECTURE.md)
- [Project Report](docs/REPORT.md)
- [Sample Session](samples/sample_session.md)

## License

No license is currently specified. Add a `LICENSE` file if you intend to distribute the project for reuse.
