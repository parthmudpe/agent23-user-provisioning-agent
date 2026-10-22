"""REAL system test (no API key needed). Requires root on a disposable Debian/Ubuntu box.
Run: sudo AGENT23_INTEGRATION=1 python3 -m tests.integration_real
Creates user 'a23demo' and group 'a23team', exercises SystemOps, then cleans up
with userdel/groupdel (cleanup commands exist only in this test, not in the agent)."""
import json
import os
import subprocess
import sys

from provisioning_agent.system_ops import SystemOps


def sh(*c):
    subprocess.run(c, capture_output=True)


def main():
    if os.environ.get("AGENT23_INTEGRATION") != "1" or os.geteuid() != 0:
        sys.exit("Refusing: set AGENT23_INTEGRATION=1 and run as root on a disposable machine.")
    ops = SystemOps(audit_path="logs/integration_audit.log")
    sh("userdel", "-r", "a23demo"); sh("groupdel", "a23team")
    try:
        steps = [
            ("create_group", lambda: ops.create_group("a23team")),
            ("create_user", lambda: ops.create_user("a23demo", ["a23team"], comment="Demo User")),
            ("add_user_to_groups", lambda: ops.add_user_to_groups("a23demo", ["users"])),
            ("modify_user lock", lambda: ops.modify_user("a23demo", lock=True)),
            ("create_directory", lambda: ops.create_directory("a23demo", "projects/web", "750")),
            ("get_user", lambda: ops.get_user("a23demo")),
        ]
        ok = True
        for name, fn in steps:
            r = fn()
            print(f"== {name}\n{json.dumps(r, indent=2)}")
            ok &= bool(r.get("verified", True))
        for bad in (lambda: ops.modify_user("root", lock=True), lambda: ops.create_user("a;b")):
            try:
                bad(); ok = False
            except Exception as e:
                print(f"== refused as expected: {type(e).__name__}: {e}")
        print("INTEGRATION", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    finally:
        sh("userdel", "-r", "a23demo"); sh("groupdel", "a23team")


if __name__ == "__main__":
    sys.exit(main())
