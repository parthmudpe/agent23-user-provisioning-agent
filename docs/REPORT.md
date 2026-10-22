# Project Report - Agent 23: User Provisioning Agent

**Objective.** A terminal AI agent that turns English requests into safe Linux user, group and
home-directory operations on Ubuntu/Debian.

**Design.** Python 3 + Anthropic Messages API tool calling. Eight tools (get_user_info,
get_group_info, list_users, create_group, create_user, add_user_to_groups, modify_user,
create_directory). Claude chooses tools; Python validates and executes. No C code is used: every
operation is available through standard utilities, so headers are unnecessary.

**Commands used.** useradd, usermod, groupadd, mkdir (via runuser so the user owns the result),
id, getent. `/etc/passwd` and `/etc/group` are never opened for writing.

**Security controls.**
1. Strict whitelist regexes for usernames, groups, comments, paths, modes (no `..`, absolute paths, setuid or world-writable).
2. argv lists with `shell=False`, minimal PATH, timeout; no string-built commands.
3. Root check before any mutation; `--dry-run` for rehearsal.
4. Operator must approve each exact command (y/N); privileged groups (sudo, docker, adm...) always ask, even with `--yes`.
5. System accounts (uid < 1000, reserved names) cannot be modified; groups must already exist.
6. Symlink and home-location checks before mkdir.
7. Append-only JSON-lines audit log.
8. Post-change verification via id, getent and stat; results report `verified`.

**Testing (executed in the build sandbox).** 29 unit tests with a simulated system: all passed.
A real integration test (`tests/integration_real.py`) ran as root against actual
useradd/usermod/groupadd/runuser/getent/id and passed; output in `samples/real_integration_output.txt`.
The live Claude loop was NOT executed in the sandbox (no API key, `anthropic` not installed);
the loop is covered by a scripted fake client. Run it yourself with your key (see README).

**Limitations.** No user deletion or password setting by design; lock state needs root
(getent shadow); one Linux host; Claude API needs network access.

**Future work.** Optional user removal with double confirmation, SSH key provisioning, batch CSV import.
