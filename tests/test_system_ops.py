import os
import shutil
import stat
import tempfile
import unittest

from provisioning_agent.system_ops import OpError, SystemOps, UserDeclined
from provisioning_agent.validators import ValidationError
from tests.fakes import FakeSystem


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.approved = []
        self.ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                             confirm=lambda c, w: self.approved.append((c, w)) or True,
                             shells_file="/nonexistent")  # falls back to /bin/bash

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_create_user_verified(self):
        r = self.ops.create_user("alice", ["developers"], comment="Alice A")
        self.assertTrue(r["verified"], r)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "alice")))
        self.assertIn("developers", r["user"]["groups"])
        self.assertEqual(self.approved[0][1], None)

    def test_privileged_group_warns(self):
        self.ops.create_user("bob", ["sudo"])
        self.assertIn("sudo", self.approved[0][1])

    def test_missing_group_rejected(self):
        with self.assertRaises(OpError):
            self.ops.create_user("carol", ["nogroup_x"])
        self.assertFalse(any(c[0] == "useradd" for c in self.fake.calls))

    def test_duplicate_and_reserved(self):
        self.ops.create_user("dave")
        with self.assertRaises(OpError):
            self.ops.create_user("dave")
        with self.assertRaises(OpError):
            self.ops.create_user("root")

    def test_injection_never_reaches_runner(self):
        for bad in ("a;rm -rf /", "$(id)", "x y", "-o"):
            with self.assertRaises(ValidationError):
                self.ops.create_user(bad)
        self.assertEqual(self.fake.calls, [])

    def test_shell_not_in_shells(self):
        with self.assertRaises(ValidationError):
            self.ops.create_user("erin", shell="/tmp/evil")

    def test_requires_root(self):
        ops = SystemOps(runner=self.fake, is_root=lambda: False, home_root=self.tmp,
                        shells_file="/nonexistent")
        with self.assertRaises(OpError) as cm:
            ops.create_user("frank")
        self.assertIn("Root", str(cm.exception))
        self.assertFalse(any(c[0] == "useradd" for c in self.fake.calls))

    def test_declined(self):
        ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                        confirm=lambda c, w: False, shells_file="/nonexistent")
        with self.assertRaises(UserDeclined):
            ops.create_user("gina")
        self.assertNotIn("gina", self.fake.users)

    def test_dry_run_changes_nothing(self):
        ops = SystemOps(runner=self.fake, dry_run=True, is_root=lambda: False, home_root=self.tmp,
                        shells_file="/nonexistent")
        r = ops.create_user("hank")
        self.assertTrue(r["dry_run"])
        self.assertNotIn("hank", self.fake.users)

    def test_group_create_and_reserved(self):
        r = self.ops.create_group("qa", gid=2500)
        self.assertTrue(r["verified"])
        with self.assertRaises(OpError):
            self.ops.create_group("sudo")
        with self.assertRaises(OpError):
            self.ops.create_group("qa")

    def test_add_to_groups_and_protect_root(self):
        self.ops.create_user("ivy")
        r = self.ops.add_user_to_groups("ivy", ["developers", "users"])
        self.assertTrue(r["verified"])
        with self.assertRaises(OpError):
            self.ops.add_user_to_groups("root", ["users"])

    def test_modify_and_lock(self):
        self.ops.create_user("jack")
        r = self.ops.modify_user("jack", comment="Jack J", lock=False)
        self.assertTrue(r["verified"], r)
        self.assertFalse(self.ops.is_locked("jack"))
        with self.assertRaises(ValidationError):
            self.ops.modify_user("jack")

    def test_create_directory(self):
        self.ops.create_user("kim")
        if os.getuid() >= 1000:  # non-root dev machine: files are owned by the current user
            self.fake.users["kim"]["uid"] = os.getuid()
        r = self.ops.create_directory("kim", "projects/web", "750")
        self.assertTrue(r["verified"], r)
        path = os.path.join(self.tmp, "kim", "projects", "web")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o750)
        with self.assertRaises(OpError):  # already exists
            self.ops.create_directory("kim", "projects/web")

    def test_directory_traversal_and_symlink(self):
        self.ops.create_user("lee")
        for bad in ("../kim", "/etc", "a/../../b"):
            with self.assertRaises(ValidationError):
                self.ops.create_directory("lee", bad)
        os.symlink("/tmp", os.path.join(self.tmp, "lee", "link"))
        with self.assertRaises(OpError):
            self.ops.create_directory("lee", "link/x")

    def test_list_users_excludes_system(self):
        self.ops.create_user("mia")
        names = [u["username"] for u in self.ops.list_users()]
        self.assertEqual(names, ["mia"])

    def test_audit_log(self):
        log = os.path.join(self.tmp, "audit.log")
        ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                        audit_path=log, shells_file="/nonexistent")
        ops.create_user("nina")
        self.assertIn("useradd", open(log).read())

    def test_never_touches_passwd_files(self):
        self.ops.create_user("omar")
        allowed = {"getent", "id", "useradd", "usermod", "groupadd", "runuser", "mkdir"}
        self.assertTrue(all(c[0] in allowed for c in self.fake.calls))


if __name__ == "__main__":
    unittest.main()
