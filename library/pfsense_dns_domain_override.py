#!/usr/bin/python
# Copyright (c) 2026
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""Manage one override without taking ownership of global Unbound settings."""
import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.pfsensible.core.plugins.module_utils.module_base import PFSenseModuleBase

DOCUMENTATION = r'''
module: pfsense_dns_domain_override
short_description: Manage an individual pfSense DNS Resolver domain override
description:
  - Repository-local module using the pinned pfsensible.core configuration helpers.
  - Preserves other overrides, host records, and resolver settings.
  - Managed overrides use plain DNS on port 53, without upstream TLS.
author: Homelab maintainers
options:
  domain:
    description: Exact domain to manage.
    type: str
    required: true
  ip:
    description: Forwarding server IPv4 or IPv6 address. Required when present.
    type: str
  state:
    description: Whether the override should exist.
    type: str
    choices: [present, absent]
    default: present
requirements:
  - pfsensible.core 0.7.1
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
'''
EXAMPLES = r'''
- name: Forward a cluster zone
  pfsense_dns_domain_override:
    domain: cluster.example.org
    ip: 192.0.2.53
    state: present
'''
RETURN = r'''
changed:
  description: Whether the override changed or would change in check mode.
  returned: always
  type: bool
'''

ARGUMENT_SPEC = dict(
    domain=dict(type='str', required=True),
    ip=dict(type='str'),
    state=dict(type='str', choices=['present', 'absent'], default='present'),
)


class DomainOverrideModule(PFSenseModuleBase):
    def __init__(self, module, pfsense=None):
        super().__init__(module, pfsense, root='unbound', root_is_exclusive=False,
                         node='domainoverrides', key='domain')

    def _validate_params(self):
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', self.params['domain']):
            self.module.fail_json(msg='Use a lowercase DNS domain without a trailing dot.')
        if self.params['state'] == 'present':
            if self.root_elt.find('enable') is None:
                self.module.fail_json(msg='Enable the DNS Resolver before adding domain overrides.')
            try:
                ipaddress.ip_address(self.params['ip'])
            except ValueError:
                self.module.fail_json(msg='ip must be an IPv4 or IPv6 address, without a port.')

    def _get_params_to_remove(self):
        # These entries are explicitly plain DNS; preserve description and other fields.
        if self.params['state'] != 'present':
            return []
        remove = ['forward_tls_upstream']
        # The GUI saves an empty hostname even with TLS off; retain that no-op field.
        if self.target_elt is not None and (self.target_elt.findtext('tls_hostname') or '').strip():
            remove.append('tls_hostname')
        return remove

    def _update(self):
        result = self.pfsense.phpshell('''
require_once("unbound.inc");
require_once("services.inc");
if (services_unbound_configure(false) != 0) { exit(1); }
clear_subsystem_dirty("unbound");
''')
        if result[0] != 0:
            self.module.fail_json(msg='Override saved but DNS Resolver reload failed; inspect pfSense and apply changes.', changed=True)
        return result


def main():
    module = AnsibleModule(argument_spec=ARGUMENT_SPEC,
                           required_if=[['state', 'present', ['ip']]], supports_check_mode=True)
    override = DomainOverrideModule(module)
    override.run(module.params)
    override.commit_changes()


if __name__ == '__main__':
    main()
