# Architecture

```mermaid
flowchart LR
    U[Operator terminal] -->|natural language| M[main.py CLI]
    M --> A[agent.py<br/>tool-calling loop]
    A <-->|messages + tool_use| C[(Claude API)]
    A -->|tool name + JSON input| D[tools.py Dispatcher]
    D --> V[validators.py<br/>whitelist validation]
    V --> O[system_ops.py SystemOps]
    O -->|1 root check| O
    O -->|2 show exact argv, ask y/N| M
    O -->|3 subprocess, shell=False| L[(Linux: useradd usermod groupadd<br/>mkdir runuser id getent)]
    O -->|4 re-query id/getent/stat| L
    O --> G[(logs/agent23_audit.log)]
    O -->|verified result or error| D --> A
```

```
 Operator --> CLI --> Agent loop <--> Claude API
                          |
                          v  tool_use
                     Dispatcher --> Validators --> SystemOps
                                                    | root check
                                                    | operator confirm (exact argv)
                                                    | subprocess (no shell)
                                                    | verify via id/getent/stat
                                                    v
                                         Linux + audit log
```

Trust boundary: Claude output is untrusted. Validation, confirmation, root check and
verification are enforced in Python, not by the prompt.
