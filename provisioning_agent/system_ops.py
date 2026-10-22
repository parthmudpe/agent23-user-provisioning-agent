"""All system interaction. Only useradd/usermod/groupadd/mkdir/id/getent/runuser are
executed (list argv, shell=False). /etc/passwd and /etc/group are never written."""
import json
import os
import shlex
import stat
import subprocess
import time
from dataclasses import dataclass

from . import config
from .validators import (ValidationError, validate_comment, validate_gid,
                         validate_group_list, validate_groupname, validate_mode,
                         validate_relpath, validate_shell, validate_username)


class OpError(RuntimeError):
    """Operation failed or was refused."""


class UserDeclined(OpError):
    """Human operator declined the command."""


@dataclass
class CommandResult:
    rc: int
    out: str = ""
    err: str = ""


def default_runner(cmd):
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, shell=False,
            timeout=config.COMMAND_TIMEOUT,
            env={"PATH": config.SAFE_PATH, "LANG": "C", "LC_ALL": "C"})
    except FileNotFoundError:
        return CommandResult(127, "", f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", "command timed out")
    return CommandResult(p.returncode, p.stdout.strip(), p.stderr.strip())


class SystemOps:
    def __init__(self, runner=default_runner, dry_run=False, confirm=None,
                 audit_path=None, is_root=None, home_root=config.HOME_ROOT,
                 shells_file=config.SHELLS_FILE):
        self.runner = runner
        self.dry_run = dry_run
        self.confirm = confirm
        self.audit_path = audit_path
        self.is_root = is_root or (lambda: os.geteuid() == 0)
        self.home_root = home_root
        self.shells_file = shells_file

    # ---- plumbing -------------------------------------------------------
    def _audit(self, cmd, rc, note=""):
        if not self.audit_path:
            return
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.audit_path)), exist_ok=True)
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                     "cmd": shlex.join(cmd), "rc": rc,
                                     "dry_run": self.dry_run, "note": note}) + "\n")
        except OSError:
            pass  # auditing must never break the operation

    def _read(self, cmd):
        r = self.runner(cmd)
        self._audit(cmd, r.rc, "read")
        return r

    def _mutate(self, cmd, warning=None):
        if self.dry_run:
            self._audit(cmd, 0, "dry-run (not executed)")
            return CommandResult(0, "[dry-run] not executed", "")
        if not self.is_root():
            raise OpError("Root privileges required. Restart the agent with sudo "
                          "(or use --dry-run).")
        if self.confirm and not self.confirm(shlex.join(cmd), warning):
            self._audit(cmd, -1, "declined by operator")
            raise UserDeclined("Operator declined to run: " + shlex.join(cmd))
        r = self.runner(cmd)
        self._audit(cmd, r.rc, "mutation")
        if r.rc != 0:
            raise OpError(f"{cmd[0]} failed (exit {r.rc}): {r.err or r.out or 'no output'}")
        return r

    # ---- queries (getent / id) -------------------------------------------
    def allowed_shells(self):
        try:
            with open(self.shells_file, encoding="utf-8") as fh:
                shells = [l.strip() for l in fh if l.strip() and not l.startswith("#")]
        except OSError:
            shells = []
        return {s for s in shells if os.path.exists(s)} or {config.DEFAULT_SHELL}

    def get_user(self, username):
        username = validate_username(username)
        r = self._read(["getent", "passwd", username])
        if r.rc != 0 or not r.out:
            return None
        f = r.out.split(":")
        if len(f) != 7:
            raise OpError("Unexpected getent passwd output.")
        g = self._read(["id", "-nG", username])
        return {"username": f[0], "uid": int(f[2]), "gid": int(f[3]), "comment": f[4],
                "home": f[5], "shell": f[6],
                "groups": g.out.split() if g.rc == 0 else [],
                "home_exists": os.path.isdir(f[5])}

    def get_group(self, groupname):
        groupname = validate_groupname(groupname)
        r = self._read(["getent", "group", groupname])
        if r.rc != 0 or not r.out:
            return None
        f = r.out.split(":")
        return {"group": f[0], "gid": int(f[2]),
                "members": [m for m in f[3].split(",") if m] if len(f) > 3 else []}

    def list_users(self):
        r = self._read(["getent", "passwd"])
        users = []
        for line in r.out.splitlines():
            f = line.split(":")
            if len(f) == 7 and config.MIN_UID <= int(f[2]) <= config.MAX_UID:
                users.append({"username": f[0], "uid": int(f[2]), "home": f[5], "shell": f[6]})
        return users

    def is_locked(self, username):
        r = self._read(["getent", "shadow", username])
        if r.rc != 0:
            return None
        pw = r.out.split(":")[1] if ":" in r.out else ""
        return pw.startswith("!")

    def _manageable(self, username):
        user = self.get_user(username)
        if user is None:
            raise OpError(f"User '{username}' does not exist.")
        if username in config.RESERVED_USERS or not config.MIN_UID <= user["uid"] <= config.MAX_UID:
            raise OpError(f"User '{username}' (uid {user['uid']}) is a protected system account.")
        return user

    def _require_groups_exist(self, groups):
        for g in groups:
            if self.get_group(g) is None:
                raise OpError(f"Group '{g}' does not exist. Create it first.")

    @staticmethod
    def _priv_warning(groups):
        priv = [g for g in groups if g in config.PRIVILEGED_GROUPS]
        return ("PRIVILEGED GROUP(S): " + ", ".join(priv) + " grant elevated system rights.") if priv else None

    # ---- mutations ---------------------------------------------------------
    def create_group(self, groupname, gid=None):
        groupname = validate_groupname(groupname)
        gid = validate_gid(gid)
        if groupname in config.RESERVED_USERS or groupname in config.PRIVILEGED_GROUPS:
            raise OpError(f"Group name '{groupname}' is reserved.")
        if self.get_group(groupname):
            raise OpError(f"Group '{groupname}' already exists.")
        cmd = ["groupadd"] + (["-g", str(gid)] if gid else []) + [groupname]
        self._mutate(cmd)
        if self.dry_run:
            return {"ok": True, "dry_run": True, "planned": shlex.join(cmd)}
        g = self.get_group(groupname)
        verified = g is not None and (gid is None or g["gid"] == gid)
        return {"ok": verified, "verified": verified, "group": g, "command": shlex.join(cmd)}

    def create_user(self, username, groups=None, shell=None, comment=""):
        username = validate_username(username)
        if username in config.RESERVED_USERS:
            raise OpError(f"Username '{username}' is reserved.")
        groups = validate_group_list(groups)
        shell = validate_shell(shell or config.DEFAULT_SHELL, self.allowed_shells())
        comment = validate_comment(comment)
        if self.get_user(username):
            raise OpError(f"User '{username}' already exists.")
        self._require_groups_exist(groups)
        cmd = ["useradd", "-m", "-s", shell, "-c", comment]
        if groups:
            cmd += ["-G", ",".join(groups)]
        cmd.append(username)
        self._mutate(cmd, self._priv_warning(groups))
        if self.dry_run:
            return {"ok": True, "dry_run": True, "planned": shlex.join(cmd)}
        u = self.get_user(username)
        uid_check = self._read(["id", "-u", username])
        checks = {
            "account_exists": u is not None,
            "id_matches_getent": bool(u) and uid_check.rc == 0 and uid_check.out == str(u["uid"]),
            "home_dir_exists": bool(u) and u["home_exists"],
            "shell_correct": bool(u) and u["shell"] == shell,
            "groups_correct": bool(u) and all(g in u["groups"] for g in groups),
        }
        verified = all(checks.values())
        return {"ok": verified, "verified": verified, "checks": checks, "user": u,
                "command": shlex.join(cmd),
                "note": "No password set: account cannot log in with a password until the admin runs 'passwd'."}

    def add_user_to_groups(self, username, groups):
        username = validate_username(username)
        groups = validate_group_list(groups)
        if not groups:
            raise ValidationError("At least one group is required.")
        self._manageable(username)
        self._require_groups_exist(groups)
        cmd = ["usermod", "-a", "-G", ",".join(groups), username]
        self._mutate(cmd, self._priv_warning(groups))
        if self.dry_run:
            return {"ok": True, "dry_run": True, "planned": shlex.join(cmd)}
        u = self.get_user(username)
        verified = bool(u) and all(g in u["groups"] for g in groups)
        return {"ok": verified, "verified": verified, "groups_now": u["groups"] if u else [],
                "command": shlex.join(cmd)}

    def modify_user(self, username, shell=None, comment=None, lock=None):
        username = validate_username(username)
        if shell is None and comment is None and lock is None:
            raise ValidationError("Nothing to change: give shell, comment, or lock.")
        self._manageable(username)
        cmd = ["usermod"]
        if shell is not None:
            shell = validate_shell(shell, self.allowed_shells())
            cmd += ["-s", shell]
        if comment is not None:
            comment = validate_comment(comment)
            cmd += ["-c", comment]
        if lock is not None:
            if not isinstance(lock, bool):
                raise ValidationError("lock must be true or false.")
            cmd.append("-L" if lock else "-U")
        cmd.append(username)
        self._mutate(cmd)
        if self.dry_run:
            return {"ok": True, "dry_run": True, "planned": shlex.join(cmd)}
        u = self.get_user(username)
        checks = {}
        if shell is not None:
            checks["shell"] = bool(u) and u["shell"] == shell
        if comment is not None:
            checks["comment"] = bool(u) and u["comment"] == comment
        if lock is not None:
            state = self.is_locked(username)
            checks["lock_state"] = state is None or state == lock
        verified = all(checks.values())
        return {"ok": verified, "verified": verified, "checks": checks, "user": u,
                "command": shlex.join(cmd)}

    def create_directory(self, username, relative_path, mode="700"):
        username = validate_username(username)
        parts = validate_relpath(relative_path)
        mode = validate_mode(mode)
        user = self._manageable(username)
        home = os.path.normpath(user["home"])
        if os.path.dirname(home) != os.path.normpath(self.home_root):
            raise OpError(f"Home '{home}' is not directly under {self.home_root}; refusing.")
        # reject symlinks along the existing part of the path (no escape from home)
        cur = home
        if os.path.islink(cur):
            raise OpError("Home directory is a symlink; refusing.")
        for p in parts:
            cur = os.path.join(cur, p)
            if os.path.islink(cur):
                raise OpError(f"Symlink in path at '{cur}'; refusing.")
        target = cur
        if os.path.lexists(target):
            raise OpError(f"'{target}' already exists.")
        cmd = ["runuser", "-u", username, "--", "mkdir", "-p", "-m", mode, target]
        self._mutate(cmd)
        if self.dry_run:
            return {"ok": True, "dry_run": True, "planned": shlex.join(cmd)}
        try:
            st = os.stat(target)
            checks = {"is_directory": stat.S_ISDIR(st.st_mode),
                      "owner_correct": st.st_uid == user["uid"],
                      "mode_correct": stat.S_IMODE(st.st_mode) == int(mode, 8)}
        except OSError:
            checks = {"is_directory": False}
        verified = all(checks.values())
        return {"ok": verified, "verified": verified, "checks": checks, "path": target,
                "command": shlex.join(cmd)}
