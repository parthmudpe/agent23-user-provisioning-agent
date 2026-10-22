import os
import shutil
import tempfile
import unittest

from provisioning_agent.agent import Agent
from provisioning_agent.system_ops import SystemOps
from provisioning_agent.tools import Dispatcher
from tests.fakes import FakeClient, FakeSystem


class DirectReadRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = FakeSystem(self.tmp)
        self.fake.users['demo1'] = dict(uid=1001, gid=1001, comment='',
                                       home=os.path.join(self.tmp, 'demo1'),
                                       shell='/bin/bash', groups=['demo1'], locked=True)
        os.makedirs(self.fake.users['demo1']['home'], exist_ok=True)
        self.fake.groups['demo1'] = 1001
        self.client = FakeClient([])
        ops = SystemOps(runner=self.fake, is_root=lambda: True, home_root=self.tmp,
                        shells_file='/nonexistent')
        self.agent = Agent(self.client, Dispatcher(ops))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_show_user_is_read_only_and_does_not_call_model(self):
        result = self.agent.ask('show me demo1')
        self.assertIn('User demo1:', result)
        self.assertIn('locked: yes', result)
        self.assertEqual(self.client.requests, [])
        self.assertFalse(any(c[0] in ('useradd', 'usermod', 'groupadd') for c in self.fake.calls))

    def test_show_user_variants_are_read_only(self):
        for request in ('show user demo1', 'get details for user demo1', 'info about demo1'):
            with self.subTest(request=request):
                result = self.agent.ask(request)
                self.assertIn('User demo1:', result)
        self.assertFalse(any(c[0] in ('useradd', 'usermod', 'groupadd') for c in self.fake.calls))

    def test_list_users_does_not_call_model(self):
        result = self.agent.ask('list users')
        self.assertIn('demo1', result)
        self.assertEqual(self.client.requests, [])


if __name__ == '__main__':
    unittest.main()
