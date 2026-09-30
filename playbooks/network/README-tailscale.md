# Tailscale on pfSense

[pfsense-tailscale.yml](pfsense-tailscale.yml) installs the pfSense-managed
Tailscale package and manages its persistent preferences. The source of truth is
[pfSense host variables](../../inventory/host_vars/pfsense.home.morey.tech.yml),
initially populated from the existing router configuration. Refer to that file
for advertised subnets, exit-node advertisement, DNS acceptance, port, and logging.

From the repository root:

```bash
ansible-galaxy collection install -r requirements.yml
ansible-playbook -i inventory/ playbooks/network/pfsense-tailscale.yml --check
ansible-playbook -i inventory/ playbooks/network/pfsense-tailscale.yml
```

The playbook uses the router's existing admin SSH connection. Use LAN access
when changing Tailscale settings: applying preferences can restart its service.
Package installation uses `state: present`; it does not request upgrades on
every run. The pfSense package repository supplies the compatible version.

The [local module](../../library/pfsense_tailscale.py) uses `pfsensible.core`
configuration helpers and the installed package's `tailscale_resync_config_hook`,
the same hook used by its settings page. It manages only the specified preferences,
preserves other package settings and authentication, and refuses to relocate an
existing state directory. It does not call the authentication cleanup hook or
delete the node state. See the [upstream package implementation](https://github.com/pfsense/FreeBSD-ports/blob/devel/security/pfSense-pkg-Tailscale/files/usr/local/pkg/tailscale/tailscale.inc).

## Authentication and fresh installations

An already connected router retains its identity and requires no new key. The
playbook does not export or commit the existing key. On a fresh installation,
it pauses for enrollment through **VPN → Tailscale → Authentication** in pfSense.
Provide an appropriate auth key in that UI and approve the device in Tailscale
if required. Press Enter only when the package status shows it is connected.
Keep keys out of Git and Ansible output; the package retains its authentication
configuration on the router.

Set `pfsense_tailscale_bootstrap_interactive: false` for unattended runs. Such
runs require the router to be authenticated already and fail with instructions
if it needs enrollment. Route and exit-node approval remain tailnet administration
steps; advertising a route alone does not grant clients permission to use it.
Existing firewall rules, ACLs, and interface assignments remain independently
managed. This playbook does not create additional network-access rules.

## Verification and DNS integration

An apply waits for the node to be online, compares effective DNS/route preferences
with inventory, and resolves the router's own MagicDNS name through Tailscale.
Status and preference output is hidden because it may contain private tailnet
information. Check mode compares package settings without restarting the service;
it skips runtime checks. When the package is absent, check mode reports its
installation but cannot validate package configuration on that host yet.

The resolver domain override is managed separately by the DNS playbook's
[`pfsense_dns` workflow](README.md#pfsense-dns-resolver-overrides). After enrollment:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags pfsense_dns
```

The Technitium conditional forwarder remains managed by `technitium_forwarding`.
The Tailscale playbook preserves the existing `acceptdns` setting; accepting
tailnet DNS and serving a conditional forwarder are separate settings.
