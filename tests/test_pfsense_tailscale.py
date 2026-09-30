"""Verify package configuration changes preserve identity and unrelated settings."""
import copy
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

for path in os.environ.get('ANSIBLE_COLLECTIONS_PATH', str(Path.home() / '.ansible/collections') + ':/usr/share/ansible/collections').split(':'):
    sys.path.insert(0, path)
from ansible_collections.pfsensible.core.plugins.module_utils.pfsense import PFSenseModule

SPEC = importlib.util.spec_from_file_location('tailscale_module', Path(__file__).resolve().parents[1] / 'library/pfsense_tailscale.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Failure(Exception):
    pass


class TailscaleTest(unittest.TestCase):
    def setUp(self):
        self.helper = object.__new__(PFSenseModule)
        self.helper.debug = Mock()
        self.helper.root = ET.fromstring('''<pfsense><installedpackages>
        <tailscaleauth><config><preauthkey>secret-fixture</preauthkey></config></tailscaleauth>
        <tailscale><config><enable>on</enable><listenport>41641</listenport><statedir>/state</statedir>
        <acceptdns>on</acceptdns><exitnode>on</exitnode><acceptroutes/><syslogenable/>
        <row><advertisedroutevalue>192.0.2.0/24</advertisedroutevalue><advertisedroutedescr>LAN</advertisedroutedescr></row>
        <autorefreshinterval>5</autorefreshinterval></config></tailscale>
        </installedpackages><unbound><enable/></unbound></pfsense>''')
        self.auth = ET.tostring(self.helper.root.find('installedpackages/tailscaleauth'))
        self.helper.write_config = Mock()
        self.helper.phpshell = Mock(return_value=(0, '', ''))
        self.settings = dict(enable=True, listenport=41641, statedir='/state', acceptdns=True, exitnode=True,
                             acceptroutes=False, syslogenable=False,
                             row=[dict(advertisedroutevalue='192.0.2.0/24', advertisedroutedescr='LAN')])

    def run_settings(self, settings=None, check=False):
        module = Mock(argument_spec=MODULE.ARGUMENT_SPEC, check_mode=check)
        module.fail_json.side_effect = lambda **kw: (_ for _ in ()).throw(Failure(kw['msg']))
        action = MODULE.TailscaleModule(module, self.helper)
        action.run({'settings': settings if settings is not None else self.settings})
        action.commit_changes()
        self.assertEqual(ET.tostring(self.helper.root.find('installedpackages/tailscaleauth')), self.auth)
        self.assertEqual(self.helper.root.findtext('installedpackages/tailscale/config/autorefreshinterval'), '5')
        return action.result

    def test_existing_gui_settings_are_unchanged(self):
        self.assertFalse(self.run_settings()['changed'])
        self.helper.write_config.assert_not_called()
        self.helper.phpshell.assert_not_called()

    def test_route_update_then_idempotent(self):
        self.settings['row'].append(dict(advertisedroutevalue='198.51.100.0/24', advertisedroutedescr='New LAN'))
        self.assertTrue(self.run_settings()['changed'])
        self.assertFalse(self.run_settings()['changed'])
        self.helper.write_config.assert_called_once()
        self.assertIn('tailscale_resync_config_hook', self.helper.phpshell.call_args.args[0])
        self.assertNotIn('clean', self.helper.phpshell.call_args.args[0])

    def test_empty_routes_clear_advertisements(self):
        self.settings['row'] = []
        self.assertTrue(self.run_settings()['changed'])
        self.assertEqual(self.helper.root.findall('installedpackages/tailscale/config/row'), [])
        self.assertFalse(self.run_settings()['changed'])

    def test_check_mode_does_not_save_or_resync(self):
        self.settings['exitnode'] = False
        self.assertTrue(self.run_settings(check=True)['changed'])
        self.helper.write_config.assert_not_called()
        self.helper.phpshell.assert_not_called()

    def test_refuses_state_relocation_and_bad_routes(self):
        for override in [dict(statedir='/new-state'), dict(row=[dict(advertisedroutevalue='192.0.2.5/24')])]:
            with self.subTest(override=override), self.assertRaises(Failure):
                self.run_settings(dict(copy.deepcopy(self.settings), **override))
        self.helper.write_config.assert_not_called()


if __name__ == '__main__':
    unittest.main()
