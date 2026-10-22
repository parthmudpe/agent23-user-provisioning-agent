import unittest
from provisioning_agent.main import looks_like_shell_command


class PromptGuardTests(unittest.TestCase):
    def test_shell_commands_detected(self):
        for line in ("sudo python3 agent23.py", "python3 agent23.py --dry-run", "./scripts/run_tests.sh",
                     "cd ~/agent23", "ls", "exit", "ollama serve"):
            self.assertTrue(looks_like_shell_command(line), line)

    def test_requests_not_flagged(self):
        for line in ("Create a new user named demo1 with a home directory.",
                     "create a group called developers", "show me demo1", "list all users",
                     "add demo1 to the sudo group", "lock demo1"):
            self.assertFalse(looks_like_shell_command(line), line)


if __name__ == "__main__":
    unittest.main()
