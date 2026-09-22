"""Test the local override module with real pfsensible XML helpers, without a router."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

# Use installed collection roots; tests require the repo's pinned pfsensible.core.
for path in os.environ.get('ANSIBLE_COLLECTIONS_PATH', str(Path.home() / '.ansible/collections') + ':/usr/share/ansible/collections').split(':'):
    sys.path.insert(0, path)
from ansible_collections.pfsensible.core.plugins.module_utils.pfsense import PFSenseModule

SPEC = importlib.util.spec_from_file_location('override', Path(__file__).resolve().parents[1] / 'library/pfsense_dns_domain_override.py')
OVERRIDE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OVERRIDE)


class ModuleFailure(Exception):
    pass


class DomainOverrideTest(unittest.TestCase):
    def setUp(self):
        self.helper = object.__new__(PFSenseModule)
        self.helper.debug = Mock()
        self.helper.root = ET.fromstring('''<pfsense><unbound><enable/><dnssec/><custom_options>unchanged</custom_options>
        <hosts><host>private</host><domain>example.org</domain><ip>192.0.2.4</ip></hosts>
        <domainoverrides><domain>other.example</domain><ip>192.0.2.5</ip></domainoverrides>
        <domainoverrides><domain>managed.example</domain><ip>192.0.2.6</ip><descr>Keep description</descr></domainoverrides>
        </unbound></pfsense>''')
        self.helper.write_config = Mock()
        self.helper.phpshell = Mock(return_value=(0, '', ''))
        self.original_others = self.unmanaged()

    def unmanaged(self):
        return [ET.tostring(e) for e in self.helper.root.find('unbound')
                if e.tag != 'domainoverrides' or e.findtext('domain') != 'managed.example']

    def run_module(self, state='present', ip='192.0.2.53', check=False):
        module = Mock(argument_spec=OVERRIDE.ARGUMENT_SPEC, check_mode=check)
        module.fail_json.side_effect = lambda **kw: (_ for _ in ()).throw(ModuleFailure(kw['msg']))
        action = OVERRIDE.DomainOverrideModule(module, self.helper)
        action.run({'domain': 'managed.example', 'ip': ip, 'state': state})
        action.commit_changes()
        self.assertEqual(self.unmanaged(), self.original_others)
        return action.result

    def test_update_preserves_other_settings_and_is_idempotent(self):
        self.assertTrue(self.run_module()['changed'])
        self.helper.write_config.assert_called_once()
        self.helper.phpshell.assert_called_once()
        self.assertEqual(self.helper.root.findtext("unbound/domainoverrides[domain='managed.example']/descr"), 'Keep description')
        self.assertFalse(self.run_module()['changed'])
        self.helper.write_config.assert_called_once()

    def test_delete_then_create(self):
        self.assertTrue(self.run_module(state='absent')['changed'])
        self.assertFalse(self.run_module(state='absent')['changed'])
        self.assertTrue(self.run_module()['changed'])
        self.assertFalse(self.run_module()['changed'])

    def test_check_mode_never_writes_or_reloads(self):
        self.assertTrue(self.run_module(check=True)['changed'])
        self.helper.write_config.assert_not_called()
        self.helper.phpshell.assert_not_called()

    def test_removes_tls_only_on_managed_override(self):
        target = self.helper.root.find("unbound/domainoverrides[domain='managed.example']")
        ET.SubElement(target, 'forward_tls_upstream')
        ET.SubElement(target, 'tls_hostname').text = 'dns.example'
        self.assertTrue(self.run_module()['changed'])
        self.assertIsNone(target.find('forward_tls_upstream'))
        self.assertIsNone(target.find('tls_hostname'))

    def test_gui_empty_tls_hostname_is_unchanged(self):
        target = self.helper.root.find("unbound/domainoverrides[domain='managed.example']")
        ET.SubElement(target, 'tls_hostname')
        self.assertFalse(self.run_module(ip='192.0.2.6')['changed'])
        self.helper.write_config.assert_not_called()

    def test_duplicate_domain_and_invalid_ip_fail(self):
        with self.assertRaises(ModuleFailure):
            self.run_module(ip='bad')
        ET.SubElement(ET.SubElement(self.helper.root.find('unbound'), 'domainoverrides'), 'domain').text = 'managed.example'
        with self.assertRaises(ModuleFailure):
            self.run_module()
        self.helper.write_config.assert_not_called()

    def test_reload_failure_is_reported_after_save(self):
        self.helper.phpshell.return_value = (1, '', 'reload failed')
        with self.assertRaisesRegex(ModuleFailure, 'reload failed'):
            self.run_module()
        self.helper.write_config.assert_called_once()

    def test_disabled_resolver_is_not_enabled(self):
        root = self.helper.root.find('unbound')
        root.remove(root.find('enable'))
        with self.assertRaisesRegex(ModuleFailure, 'Enable the DNS Resolver'):
            self.run_module()
        self.helper.write_config.assert_not_called()


if __name__ == '__main__':
    unittest.main()
