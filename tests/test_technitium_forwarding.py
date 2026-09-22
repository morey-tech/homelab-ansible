"""Exercise the real Ansible forwarding tasks against a local fake API."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'fixture-token-must-not-appear'


class ForwardingTest(unittest.TestCase):
    def setUp(self):
        self.zones = {
            'same.example': {'type': 'Forwarder', 'disabled': False},
            'drift.example': {'type': 'Forwarder', 'disabled': False},
        }
        def record(address):
            return {'type': 'FWD', 'disabled': False, 'rData': {
                'forwarder': address, 'protocol': 'Udp', 'dnssecValidation': False, 'proxyType': 'NoProxy'}}
        self.records = {'same.example': [record('192.0.2.1')], 'drift.example': [record('192.0.2.2')]}
        self.writes = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.headers.get('Authorization') != 'Bearer ' + TOKEN:
                    self.send_error(403)
                    return
                body = parse_qs(self.rfile.read(int(self.headers.get('Content-Length', 0))).decode())
                body = {key: value[0] for key, value in body.items()}
                zone = body.get('zone')
                response = {}
                if self.path == '/api/zones/list':
                    # Include a similar name to exercise exact zone matching.
                    response = {'zones': [{'name': name, **data} for name, data in fixture.zones.items()]
                                + [{'name': 'child.new.example', 'type': 'Primary', 'disabled': False}]}
                elif self.path == '/api/zones/records/get':
                    response = {'records': fixture.records[zone]}
                elif self.path in ['/api/zones/create', '/api/zones/records/add']:
                    fixture.writes.append((self.path, body))
                    fixture.zones[zone] = {'type': 'Forwarder', 'disabled': False}
                    fixture.records[zone] = [record(body['forwarder'])]
                else:
                    self.send_error(404)
                    return
                content = json.dumps({'status': 'ok', 'response': response}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(content)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name)
        (path / 'ansible.cfg').write_text('[defaults]\n')
        tasks = (ROOT / 'playbooks/network/tasks/technitium-conditional-forwarder.yml').read_text()
        (path / 'tasks.yml').write_text(tasks.replace('127.0.0.1:5380', f'127.0.0.1:{self.server.server_port}'))
        (path / 'play.yml').write_text(json.dumps([{
            'hosts': 'localhost', 'gather_facts': False, 'connection': 'local',
            'vars': {'technitium_api_token': TOKEN, 'technitium_conditional_forwarders': [
                {'zone': zone, 'forwarder': '192.0.2.1'} for zone in ['same.example', 'drift.example', 'new.example']]},
            'tasks': [{'ansible.builtin.import_tasks': 'tasks.yml'}],
        }]))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def run_play(self, check=False):
        env = dict(os.environ, ANSIBLE_CONFIG=self.temp.name + '/ansible.cfg', ANSIBLE_LOCAL_TEMP=self.temp.name + '/ansible',
                   ANSIBLE_NOCOLOR='1', ANSIBLE_STDOUT_CALLBACK='default')
        result = subprocess.run(['ansible-playbook', '-i', 'localhost,', self.temp.name + '/play.yml']
                                + (['--check'] if check else []), env=env, capture_output=True, text=True, timeout=90)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        return result

    def test_apply_then_idempotent(self):
        result = self.run_play()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual([(path, body['zone']) for path, body in self.writes], [
            ('/api/zones/create', 'new.example'), ('/api/zones/records/add', 'drift.example')])
        for _, body in self.writes:
            self.assertEqual(body['protocol'], 'Udp')
            self.assertEqual(body['dnssecValidation'], 'false')
            self.assertEqual(body['proxyType'], 'NoProxy')
        self.assertIn('Created new.example', result.stdout)
        self.assertIn('Updated drift.example', result.stdout)
        self.writes.clear()
        result = self.run_play()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.writes, [])
        self.assertIn('changed=0', result.stdout)

    def test_check_mode_reports_domains_without_writes(self):
        before = copy.deepcopy(self.records)
        result = self.run_play(check=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for message in ['unchanged: same.example', 'update: drift.example', 'create: new.example']:
            self.assertIn(message, result.stdout)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.records, before)

    def test_conflicting_or_disabled_zone_aborts_before_writes(self):
        for override in [{'type': 'Primary'}, {'disabled': True}]:
            with self.subTest(override=override):
                self.zones['drift.example'] = {'type': 'Forwarder', 'disabled': False, **override}
                result = self.run_play()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('drift.example has a conflicting zone type or is disabled', result.stdout)
                self.assertEqual(self.writes, [])


if __name__ == '__main__':
    unittest.main()
