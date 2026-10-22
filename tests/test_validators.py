import unittest
from provisioning_agent import validators as v


class ValidatorTests(unittest.TestCase):
    def test_username_ok(self):
        for n in ("alice", "bob_1", "_svc", "a-b", "x" * 32):
            self.assertEqual(v.validate_username(n), n)

    def test_username_bad(self):
        for n in ("", "Alice", "1abc", "-rf", "a b", "a;b", "a$(id)", "x" * 33, "root:x", "a\nb", None, 5):
            with self.assertRaises(v.ValidationError, msg=repr(n)):
                v.validate_username(n)

    def test_group_list(self):
        self.assertEqual(v.validate_group_list(["a", "b", "a"]), ["a", "b"])
        with self.assertRaises(v.ValidationError):
            v.validate_group_list("sudo")
        with self.assertRaises(v.ValidationError):
            v.validate_group_list(["ok", "bad name"])

    def test_comment(self):
        self.assertEqual(v.validate_comment("Alice B. O'Neil"), "Alice B. O'Neil")
        for c in ("a:b", "a,b", "a\nb", "x" * 65, "$(id)"):
            with self.assertRaises(v.ValidationError, msg=c):
                v.validate_comment(c)

    def test_gid(self):
        self.assertEqual(v.validate_gid(2000), 2000)
        for g in (0, 999, 70000, "1500", True, 1.5):
            with self.assertRaises(v.ValidationError):
                v.validate_gid(g)

    def test_shell(self):
        self.assertEqual(v.validate_shell("/bin/bash", {"/bin/bash"}), "/bin/bash")
        with self.assertRaises(v.ValidationError):
            v.validate_shell("/tmp/evil", {"/bin/bash"})

    def test_mode(self):
        self.assertEqual(v.validate_mode(None), "700")
        self.assertEqual(v.validate_mode("750"), "750")
        for m in ("777", "4755", "1777", "7", "abc", "0o77", "702"):
            with self.assertRaises(v.ValidationError, msg=m):
                v.validate_mode(m)

    def test_relpath(self):
        self.assertEqual(v.validate_relpath("projects/web"), ["projects", "web"])
        self.assertEqual(v.validate_relpath("./a//b"), ["a", "b"])
        for p in ("../etc", "/etc", "a/../b", "", "a b", "a/.hidden-ok/..", "-x", "a;b", "~/x"):
            if p == "a/.hidden-ok/..":
                with self.assertRaises(v.ValidationError):
                    v.validate_relpath(p)
                continue
            with self.assertRaises(v.ValidationError, msg=p):
                v.validate_relpath(p)


if __name__ == "__main__":
    unittest.main()
