#!/usr/bin/python
# Copyright (c) 2026
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
"""Manage package preferences using pfSense's own Tailscale resync hook."""
import ipaddress
import os

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.pfsensible.core.plugins.module_utils.module_base import PFSenseModuleBase

DOCUMENTATION = r'''
module: pfsense_tailscale
short_description: Manage pfSense Tailscale package preferences
description:
  - Updates only installedpackages/tailscale/config and invokes the package resync hook.
  - Does not manage authentication or erase the existing node identity.
author: Homelab maintainers
options:
  settings:
    description: Package preferences using pfSense GUI field names.
    type: dict
    required: true
    suboptions:
      enable:
        description: Enable the package service.
        type: bool
      listenport:
        description: UDP listen port.
        type: int
      statedir:
        description: Persistent state directory. Relocating existing state is refused.
        type: path
      keepconfig:
        description: Preserve configuration on package removal.
        type: bool
      acceptdns:
        description: Accept tailnet DNS settings.
        type: bool
      exitnode:
        description: Advertise exit-node capability.
        type: bool
      acceptroutes:
        description: Accept advertised subnet routes from peers.
        type: bool
      row:
        description: Advertised subnet routes.
        type: list
        elements: dict
        suboptions:
          advertisedroutevalue:
            description: Canonical subnet CIDR.
            type: str
            required: true
          advertisedroutedescr:
            description: Route description.
            type: str
            default: ''
      syslogenable:
        description: Enable syslog output.
        type: bool
      syslogpriority:
        description: Syslog priority.
        type: str
      syslogfacility:
        description: Syslog facility.
        type: str
requirements:
  - pfsensible.core 0.7.1
  - pfSense-pkg-Tailscale
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
'''
EXAMPLES = r'''
- name: Enable Tailscale
  pfsense_tailscale:
    settings:
      enable: true
'''
RETURN = r'''
changed:
  description: Whether package settings changed or would change in check mode.
  type: bool
  returned: always
'''
BOOL_FIELDS = ['enable', 'keepconfig', 'acceptdns', 'exitnode', 'acceptroutes', 'syslogenable']
SETTINGS_SPEC = {name: dict(type='bool') for name in BOOL_FIELDS}
SETTINGS_SPEC.update(
    listenport=dict(type='int'), statedir=dict(type='path'),
    row=dict(type='list', elements='dict', options=dict(
        advertisedroutevalue=dict(type='str', required=True),
        advertisedroutedescr=dict(type='str', default=''))),
    syslogpriority=dict(type='str', choices=['emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug']),
    syslogfacility=dict(type='str', choices=['daemon', 'user'] + ['local' + str(i) for i in range(8)]),
)
ARGUMENT_SPEC = dict(settings=dict(type='dict', required=True, options=SETTINGS_SPEC))


class TailscaleModule(PFSenseModuleBase):
    def __init__(self, module, pfsense=None):
        super().__init__(module, pfsense, root='installedpackages/tailscale', create_root=True, node='config')

    def _find_target(self):
        matches = self.root_elt.findall('config')
        if len(matches) > 1:
            self.module.fail_json(msg='Multiple Tailscale configuration entries found; review in pfSense.')
        return matches[0] if matches else None

    def _get_obj_name(self):
        return 'tailscale'

    def _log_fields(self, before=None):
        return ''

    def _validate_params(self):
        settings = self.params['settings']
        if settings.get('listenport') is not None and not 1 <= settings['listenport'] <= 65535:
            self.module.fail_json(msg='listenport must be between 1 and 65535.')
        for route in settings.get('row') or []:
            try:
                ipaddress.ip_network(route['advertisedroutevalue'], strict=True)
            except ValueError:
                self.module.fail_json(msg='Advertised routes must be canonical subnet CIDRs.')
        old_path = self.root_elt.findtext('config/statedir')
        new_path = settings.get('statedir')
        if new_path and (not os.path.isabs(new_path) or any(c in new_path for c in '\n\r"$`')):
            self.module.fail_json(msg='statedir must be a plain absolute path.')
        if old_path and new_path and old_path != new_path:
            self.module.fail_json(msg='Moving existing Tailscale state requires a separate migration.')

    def _params_to_obj(self):
        return {key: ('on' if value else '') if key in BOOL_FIELDS else str(value) if key == 'listenport' else value
                for key, value in self.params['settings'].items() if value is not None}

    def _update(self):
        result = self.pfsense.phpshell('''
require_once("tailscale/tailscale.inc");
tailscale_resync_config_hook();
''', debug=False)
        if result[0] != 0:
            self.module.fail_json(msg='Tailscale settings saved but the package resync hook failed.', changed=True)
        return result


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC, supports_check_mode=True)
    if not os.path.isfile('/usr/local/pkg/tailscale/tailscale.inc'):
        module.fail_json(msg='Install pfSense-pkg-Tailscale before configuring it.')
    action = TailscaleModule(module)
    action.run(module.params)
    action.commit_changes()


if __name__ == '__main__':
    main()
