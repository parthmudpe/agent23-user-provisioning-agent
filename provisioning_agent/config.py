"""Configuration and constants."""
import os

DEFAULT_MODEL = "llama3.2:3b"
MAX_AGENT_STEPS = 10
MAX_TOKENS = 1500
COMMAND_TIMEOUT = 20
DEFAULT_SHELL = "/bin/bash"
HOME_ROOT = "/home"
MIN_UID = 1000          # only regular (non-system) accounts are manageable
MAX_UID = 60000
SHELLS_FILE = "/etc/shells"

# Names that can never be created or modified through the agent.
RESERVED_USERS = frozenset({
    "root", "daemon", "bin", "sys", "sync", "games", "man", "lp", "mail",
    "news", "uucp", "proxy", "www-data", "backup", "list", "irc", "gnats",
    "nobody", "sshd", "systemd-network", "systemd-resolve", "messagebus",
    "syslog", "_apt", "admin", "administrator",
})

# Membership grants elevated rights: always needs explicit human warning-confirm.
PRIVILEGED_GROUPS = frozenset({
    "root", "sudo", "wheel", "adm", "shadow", "disk", "docker", "lxd",
    "staff", "kmem", "admin", "systemd-journal", "video", "libvirt",
})

SAFE_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def load_env_file(path=None):
    """Tiny .env loader (no extra dependency). Existing env vars win."""
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
