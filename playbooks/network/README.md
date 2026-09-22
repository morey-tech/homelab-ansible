# DNS and Technitium

[dns.yml](dns.yml) provisions the DNS hosts and configures Technitium. Run all
commands below from the repository root (`/workspaces/homelab-ansible`), not
from this directory.

Before the first run:

1. Complete the [QNAP VM creation runbook](vm-create/README.md) through SSH,
   sudo, and Ansible connectivity verification.
2. Follow the [controller setup](../../README.md#local-development-setup) for
   collections and the untracked `vault-password.txt`. `ansible.cfg` selects
   that password file automatically; AAP uses its injected Vault credential.
3. Check the [inventory](../../inventory/dns.yml),
   [DNS variables](../../inventory/group_vars/dns.yml), and
   [node settings](../../inventory/host_vars/dns-01.yml).
4. Save the Cloudflare token in the encrypted credential file described below.
   HTTPS is enabled by default, so a full configuration run requires it.
   The Technitium API token can be added at the first-run pause after installation.

## Configuration sources

This guide explains the workflow. Follow the linked source files for current
values; YAML examples below illustrate the shape of a setting, not the deployed
configuration. Inventory overrides and AAP/extra variables can change the values
used by a run.

| Configuration | Source of truth |
| --- | --- |
| Active nodes, primary/secondary membership, SSH address and user | [DNS inventory](../../inventory/dns.yml) |
| Per-node address suffix, VM flag, interface and connection profile | [dns-01 variables](../../inventory/host_vars/dns-01.yml), [dns-02 variables](../../inventory/host_vars/dns-02.yml) |
| Native networking, VLANs and firewall zones | [DNS group variables](../../inventory/group_vars/dns.yml): `dns_native_*`, `dns_vlans`, `dns_firewall_zone` |
| Pinned release, download URL and checksum | [DNS group variables](../../inventory/group_vars/dns.yml): `technitium_version`, `technitium_archive_*` |
| Upstreams and protocol | [DNS group variables](../../inventory/group_vars/dns.yml): `technitium_forwarders`, `technitium_forwarder_protocol` |
| Block list URLs, enablement and update interval | [DNS group variables](../../inventory/group_vars/dns.yml): `technitium_blocklist_urls`, `technitium_blocking_enabled`, `technitium_blocklist_update_interval_hours` |
| Conditional zones and query-log retention | [DNS group variables](../../inventory/group_vars/dns.yml): `technitium_conditional_forwarders`, `technitium_query_log_settings` |
| HTTPS enablement, hostname, port and contact email | [DNS group variables](../../inventory/group_vars/dns.yml): `technitium_web_*`, `technitium_certbot_email` |
| API and Cloudflare credentials | [Encrypted credentials](vars/technitium-credentials.vault.yml), or documented environment/AAP overrides |
| Private allowed domains | [Encrypted exceptions](vars/technitium-vault.yml): `technitium_allowed_domains` |
| Installation packages, service paths, firewall ports and public test defaults | [DNS playbook](dns.yml) and [installation tasks](tasks/technitium-install.yml) |

## Run and upgrade

A full run upgrades installed OS packages, installs baseline tools and Technitium,
configures networking, and starts the services:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml
```

Add `--ask-become-pass` if the SSH user requires a sudo password. The VM
creation runbook sets up passwordless sudo.

Technitium uses the [official manual installation procedure](https://blog.technitium.com/2017/11/running-dns-server-on-ubuntu-linux.html)
with the runtime dependency and service layout defined in [dns.yml](dns.yml).
The desired release, archive URL, and checksum come from
[DNS group variables](../../inventory/group_vars/dns.yml). The playbook reads the installed application's version metadata and
installs or upgrades only when it is older; equal or newer versions are left
alone. Update the version and archive checksum together for a future release.

The upstream portable archive URL tracks the latest release. Its SHA-256 is
pinned in inventory, and the embedded version is checked before DNS is stopped.
If upstream replaces the download, a checksum mismatch fails safely; retain the
cached archive or supply a trusted mirror URL for repeatable older installs.

Existing installations are stopped briefly for a consistent backup of binaries,
`/etc/dns` (including apps, query databases, and private settings), and the
systemd unit. Backups stay under `/var/backups/technitium/` in root-only
permissions and are never copied to Git. The service is started again even if
an upgrade task fails. Backups are retained for manual recovery; automatic
rollback is not performed. The upgraded web console and DNS TCP port are checked.

Preview or apply an upgrade to an already provisioned host without an API token:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags technitium_upgrade --check
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags technitium_upgrade
```

Use a full run for first installation so dependencies, directories, and initial
service setup are included. Add `--ask-become-pass` when required.

The [networking tasks](tasks/network-addresses.yml) create and assign the
native firewall zone. [dns.yml](dns.yml) defines the service ports and checks
controller connectivity. Use the URL printed by the API-token bootstrap pause
for initial console access; it selects an available HTTPS or HTTP endpoint.
When systemd-resolved is running, the playbook disables its DNS stub listener
and points a stub resolver symlink at the upstream resolver list. Host resolver
addresses come from `dns_native_resolvers` in
[DNS group variables](../../inventory/group_vars/dns.yml).

## DNS nodes and future clustering

The [inventory](../../inventory/dns.yml) defines active nodes and their roles.
The playbook provisions all hosts in `dns`, sends shared API configuration only
to the single host in `dns_primary`, and tests public resolution and blocking
on every active node. Provisioning runs one host at a time in reverse name
order, intended to upgrade secondaries before the primary.

For VM creation through working Ansible access, follow the separate
[QNAP VM creation runbook](vm-create/README.md). Its screenshots record one
installation; use the inventory for current addresses. Bootstrap the guest at
its inventory address using a DHCP reservation or installer static settings.
The playbook then enforces static native IPv4 and disables DHCP. Confirm the
interface and NetworkManager profile in the node's host variables match the
created VM before running.

The future Raspberry Pi's settings are in
[dns-02 host variables](../../inventory/host_vars/dns-02.yml). A host-vars file
alone does not activate a host. Before adding it to `dns_secondary`, confirm OS
support, interface, and NetworkManager profile. Provisioning uses Fedora/RHEL
package names; Debian/Raspberry Pi OS needs package support added first.

Cluster initialization and joining are deferred until the second node is ready.
Follow [Technitium's clustering procedure](https://blog.technitium.com/2025/11/understanding-clustering-and-how-to.html)
to choose the cluster domain, enable HTTPS, initialize `dns-01`, and join
`dns-02`. Common settings, apps, and allow/block lists synchronize from the
primary; node-specific settings and query data remain local. Add the managed
conditional-forwarding zones to the cluster catalog so they also replicate;
existing standalone zones do not join it automatically. Merely adding a host
to the Ansible inventory does not join it to the Technitium cluster.

## DNS addresses on native and tagged VLANs

`--tags network_addresses` manages the hostname, NetworkManager profiles, and
DNS firewall rules. Read `dns_native_address`, `dns_native_gateway`,
`dns_native_resolvers`, and `dns_vlans` in
[DNS group variables](../../inventory/group_vars/dns.yml), together with the
[node-specific interface and address suffix](../../inventory/host_vars/dns-01.yml).
The native interface retains only its intended static IPv4 address after apply.

For example, a VLAN entry has this shape (illustrative values only):

```yaml
dns_vlans:
  - id: 10
    connection: EXAMPLE
    address: "192.0.2.53/24"
    zone: example-dns
```

The VM's switch/hypervisor connection must carry the VLANs declared in inventory.
Tagged profiles disable IPv6 and never supply a default route. Each uses its
own firewall zone with DNS allowed; the native network retains management
access. [VLAN tasks](tasks/network-vlan.yml) enable duplicate-address detection
before activation. [Networking tasks](tasks/network-addresses.yml) back up the
original profiles in a protected directory before managing them.

All VLANs listed in `dns_vlans` are activated with autoconnect enabled. To apply
network configuration changes, run:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags network_addresses
```

Removing an entry from inventory does not delete its existing NetworkManager
profile; retire unused profiles explicitly.

## Technitium configuration as code

Upstream servers and protocol are declared by `technitium_forwarders` and
`technitium_forwarder_protocol` in
[DNS group variables](../../inventory/group_vars/dns.yml). The playbook uses
Technitium's [documented HTTP API](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md)
with Ansible's built-in `uri` module. It reads current settings and writes only
when managed settings differ. Block list URLs, blocking enablement, and the
automatic update interval are also declared in that inventory file. Manual changes to these settings are overwritten
on the next configuration run.

A full first run installs and starts Technitium before checking API credentials.
If the token is missing or rejected, an interactive run pauses with instructions
for creating a token named **homelab-ansible** in the console. Change the initial
admin password first. In a second terminal, save the token directly into Vault:

```bash
ansible-vault edit playbooks/network/vars/technitium-credentials.vault.yml
```

Set the encrypted `technitium_api_token` value, save, then press Enter in the
paused playbook. It reloads the encrypted file and validates the token before
continuing. Never paste a token into the pause prompt. Subsequent runs load it
automatically. The credential file is separate from the private domain rules.

Use an administrator token or a dedicated automation user with Settings
View/Modify, Apps View/Modify/Delete, Allowed View/Modify/Delete, and Zones
View/Modify plus View/Modify on managed zones. `TECHNITIUM_API_TOKEN` or an
explicit `technitium_api_token` override takes precedence over Vault; a rejected
override must be removed and the playbook restarted. Only encrypted credentials
belong in Git. API requests run on the VM over loopback, with secrets and API
responses suppressed from output.

For AAP/unattended runs, set `technitium_api_bootstrap_interactive: false` and
provide a valid credential in advance. Check mode never prompts. Test just
credential loading and authentication with `--tags technitium_api_auth`.
Technitium's supported token-creation API requires a user password or login
session; host root access alone is not a documented authentication mechanism.
A fully automatic bootstrap could use an admin password held in Vault, but this
workflow uses the one-time console step and retains only the API token.

With the API token and Cloudflare token supplied, preview and apply the DNS
configuration (including web HTTPS):

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags technitium_config --check
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags technitium_config
```

Add `--ask-become-pass` if sudo requires a password. To provision without any
API configuration, use `--skip-tags technitium_config`; later resume with
`--tags technitium_config`. To manage DNS configuration while deferring HTTPS,
add `--skip-tags technitium_web_tls`. Check mode requires a running Technitium instance
and valid token so it can read the current settings; it makes no API writes.

After configuration, the playbook uses `dig` on the VM to check that Technitium
returns a successful response with an IPv4 answer over both UDP and TCP.
Set `technitium_test_domain` to choose the public test name; its default is in
[dns.yml](dns.yml).
These checks skip check mode and do not report changes. They test resolution
(which may use the cache), not which upstream or encryption protocol was used.
Run the DNS checks using `--tags technitium_test`. The private exception tests
included by this tag additionally require the Vault password and an API token.

The playbook also queries `technitium_blocklist_test_domain` over UDP and TCP and requires
Technitium's EDNS `Blocked` response with `source=block-list-zone` attribution.
This proves a downloaded list is blocking the domain, rather than accepting an
ordinary NXDOMAIN or failed lookup. Configuration enables `allowTxtBlockingReport`
to expose this diagnostic information. The test retries to allow asynchronous
list downloads; see [dns.yml](dns.yml) for the test domain, retry, and delay
defaults. Override `technitium_blocklist_test_retries` or
`technitium_blocklist_test_domain` if needed. It skips check mode and disabled
or empty block list configurations. Run only this check without an API token
using `--tags technitium_blocklist_test`. This is a smoke test, not verification
that every list downloaded successfully or every rule is supported.

Technitium refreshes block lists itself at the interval configured by
`technitium_blocklist_update_interval_hours` in
[DNS group variables](../../inventory/group_vars/dns.yml); no cron job or recurring Ansible
run is needed. The URL list is authoritative: configuration replaces the current
URL list with `technitium_blocklist_urls`. New URLs are downloaded asynchronously
by Technitium, so a successful API call does not confirm successful downloads.
Check Technitium's logs for list download and parsing results. Other blocking
settings, including the response type and bypass list, are left unchanged.

For the active URLs, use `technitium_blocklist_urls` in
[DNS group variables](../../inventory/group_vars/dns.yml). For example, the
setting accepts a list like this (illustrative URL, not a working feed):

```yaml
technitium_blocklist_urls:
  - https://example.org/dns-blocklist.txt
```

Identical behavior to AdGuard Home is not guaranteed. Technitium supports hosts
files, domain lists, and a subset of Adblock syntax. Review wildcard, regex,
and AdGuard-specific modifiers in a feed before relying on equivalent coverage;
use server logs and DNS tests to validate the selected lists.

## Web console HTTPS with Let's Encrypt

The DNS playbook uses Certbot and the Cloudflare DNS plugin, following the same
DNS validation approach as the UniFi playbook. It enables Technitium's native
web listener at `https://<technitium_web_domain>:<technitium_web_tls_port>/`.
Use the values in [DNS group variables](../../inventory/group_vars/dns.yml).
Local DNS must resolve the certificate name to the node's inventory address
from the controller and browser. DNS validation
creates temporary public TXT records; it requires no inbound Internet port
forwarding to the VM.

Set `cloudflare_dns_edit_api_token` in the existing encrypted credential file:

```bash
ansible-vault edit playbooks/network/vars/technitium-credentials.vault.yml
```

Keep the existing `technitium_api_token` entry. Alternatively, inject
`cloudflare_dns_edit_api_token` through an AAP credential, as with UniFi.
Use a Cloudflare token with DNS Edit permission for the authoritative
zone containing the configured certificate name. The token is deployed root-only with task output and diffs
suppressed. Do not put it in plaintext inventory.

The certificate name, port, and contact email are configured with
`technitium_web_domain`, `technitium_web_tls_port`, and
`technitium_certbot_email` in
[DNS group variables](../../inventory/group_vars/dns.yml). Run against an installed Technitium instance:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags technitium_web_tls
```

A full run also includes these tasks. API authentication happens first: a fresh
installation's token-creation pause shows the HTTP URL. If trusted HTTPS is
already reachable, the pause shows the HTTPS URL instead. HTTPS is enabled
through the authenticated settings API once the token is available.

Certbot's Fedora `certbot-renew.timer` handles automatic renewal. A deploy hook
converts the certificate and private key to `/etc/dns/webui.pfx`, readable only
by root and the `dns-server` group, and atomically replaces it when the leaf
certificate changes. Technitium automatically reloads the changed certificate;
renewal does not restart the DNS service. The playbook also repairs a missing
or stale PFX and verifies the HTTPS page from the controller with certificate
and hostname validation enabled. For example, test renewal after initial issuance
using the SSH target and certificate name from inventory:

```bash
ssh <ssh-user>@<node-address> 'sudo certbot renew --cert-name <web-domain> --dry-run'
```

HTTP on port 5380 remains available for bootstrap and the existing loopback API
calls; automatic HTTP-to-HTTPS redirection is disabled. HTTPS is opened only
in the native management firewall zone. This configures the web console,
not DNS-over-HTTPS or DNS-over-TLS. Setting `technitium_web_tls_enabled: false`
skips management; it does not remove an existing certificate or listener.

These tasks currently target `dns_primary`. When adding `dns-02`, configure its
node-specific web certificate as part of cluster setup; the primary node's
certificate does not automatically cover a different node name.

References: [Cloudflare DNS validation](https://certbot-dns-cloudflare.readthedocs.io/en/stable/),
[Technitium settings API](https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md),
[Technitium certificate conversion and renewal](https://blog.technitium.com/2020/07/how-to-host-your-own-dns-over-https-and.html).

## Private DNS exceptions

Domain-wide exceptions are stored in the fully encrypted Ansible Vault file
[technitium-vault.yml](vars/technitium-vault.yml). It uses the local vault password
and is safe to commit while encrypted. Local configuration runs automatically
use `vault-password.txt`; supply a Vault credential when running through AAP.

Setting the encrypted variable `technitium_allowed_domains` to `null` leaves
allowed zones unmanaged. A list of lowercase domain names is authoritative for
Technitium's Allowed Zones: missing domains are
added and domains absent from the list are removed. An empty list removes all
allowed zones. A domain exception also allows its subdomains.

AdGuard rules of the form `@@||domain^` map to these entries. Private migration
input can be placed in `var/adguard-custom-rules.txt`; `/var/` is ignored by Git.
Do not put rule contents in plaintext inventory or task files. The staging file
is still plaintext locally; remove it after successful encryption and validation.

Edit the encrypted configuration using:

```bash
ansible-vault edit playbooks/network/vars/technitium-vault.yml
```

The API token additionally needs **Allowed: View, Modify, and Delete** permissions.
Run just exception management with `--tags technitium_exceptions`, adding
`--check` for a preview. Sensitive tasks suppress logs and diffs and use HTTP
request bodies over the VM's loopback interface. Vault protects repository
storage; Technitium must still retain the effective domain rules on the VM.

Exception configuration runs also verify that every encrypted domain appears
in Technitium's Allowed Zones, then query a random sample over UDP and TCP
sequentially on the primary node. The sample size is controlled by
`technitium_allowed_test_sample_size` in
[DNS group variables](../../inventory/group_vars/dns.yml). A new sample is chosen
each run; lists smaller than the requested sample are tested in full. Timeout and retry behavior are defined in the
[allowed-domain test tasks](tasks/technitium-test-allowed-domains.yml).
The tests reject blocking reports, `0.0.0.0` answers, SERVFAIL, and timeouts. A normal empty or
NXDOMAIN response is accepted: allowing a domain does not guarantee it has an
A record. All private test data, loop items, and responses are suppressed from
Ansible output. Tests skip check mode and unmanaged or empty exception lists.
Run them independently with `--tags technitium_allowed_test`; this requires the
Vault password and an API token with **Allowed: View** permission and makes no
configuration changes.

## Searchable query logs

The Query Logs page requires a DNS app that provides a query log database.
The playbook installs **Query Logs (Sqlite)** using the server's app store
catalog and enables logging through the official app configuration API.
Retention is declared by `technitium_query_log_settings` in
[DNS group variables](../../inventory/group_vars/dns.yml). Cleanup can remove
records before the age limit when the record-count limit is reached. Other app settings are preserved;
existing installations are not automatically upgraded.

The token needs **Apps: View, Modify, and Delete**; Technitium requires Delete
permission for app installation. Run just this configuration using
`--tags technitium_query_logs`, then refresh the Query Logs page. Logging starts
when the app is enabled; earlier queries are not recovered. Query history is
stored on the VM, not in Git.

## Conditional forwarding for local domains

After exception verification, configuration manages the Forwarder zones listed
in `technitium_conditional_forwarders` in
[DNS group variables](../../inventory/group_vars/dns.yml), including their
subdomains. For example (illustrative values only):

```yaml
technitium_conditional_forwarders:
  - zone: internal.example.org
    forwarder: 192.0.2.1
```

Queries for each zone go to its specified forwarder; other queries continue
using the configured public upstreams. See the
[conditional-forwarding tasks](tasks/technitium-conditional-forwarder.yml)
for record and transport settings. Forwarder records use
`NoProxy` and disable DNSSEC validation for these local zones only, allowing the
router's private answers. The token needs **Zones: View and Modify**, plus
**View and Modify** on existing managed zones. The playbook refuses conflicting
zone types or disabled zones. It manages each listed zone's apex FWD record set;
unrelated records and zones removed from inventory are not deleted automatically.

Run the normal `--tags technitium_config` workflow to verify exceptions first.
For subsequent forwarding-only runs, use `--tags technitium_forwarding` (or add
`--check` to preview). This narrower tag does not run the exception tests.
Forwarding tasks process all configured domains at each stage, validating zone
types and reading records before making changes. A domain-labelled plan shows
`create`, `update`, or `unchanged`; successful writes are reported by domain.
API requests and responses remain hidden to protect credentials and zone data.

## OCP DNS management

The shared [Technitium zone role](../../roles/technitium_zone/tasks/main.yml)
creates missing Primary zones and imports managed record sets through the API.
It refuses conflicting zone types or disabled zones, validates SOA timers and
TTLs before writing, and preserves unrelated record sets. Removing a record
from the input does not delete it remotely. SOA serials are managed by Technitium;
re-running with equivalent records makes no configuration writes.

Existing zones are exported to `/var/backups/technitium/records/` before changes,
with root-only permissions and prior backup versions retained. Each apply checks
authoritative A answers over UDP and TCP, including wildcard application names.
The token needs Zones View/Modify and View/Modify on existing managed zones.
Zone data and credentials are suppressed in output. After an unsuccessful import,
correct the error and rerun to complete any partially populated zone. Check mode
validates inputs and compares records but does not exercise API writes.

The nameserver A record uses `technitium_ocp_nameserver_address` from
[DNS group variables](../../inventory/group_vars/dns.yml), derived from the
primary's RH_LAB VLAN address independently of its Ansible management address.

The OCP DNS tasks add a pfSense DNS Resolver domain override after verifying
the Technitium zone, pointing to that nameserver address. Do not forward the broad
parent domain to Technitium: its parent conditional forwarder sends unresolved
names back to pfSense and would create a loop. Test API and application names
through pfSense after adding or removing overrides.

[baremetal-ocp-prepare.yml](../ocp/baremetal-ocp-prepare.yml) and
[ms-ocp-create.yml](../ocp/ms-ocp-create.yml) now share
[Technitium DNS tasks](../ocp/tasks/technitium-dns.yml). Cluster and node records
come from the OCP inventory; SOA/TTL defaults come from `technitium_ocp_*` in
[DNS group variables](../../inventory/group_vars/dns.yml). SNO uses the node
address, while a highly available cluster uses its API and ingress VIPs.

To manage only the DNS portion of an existing bare-metal cluster:

```bash
ansible-playbook -i inventory/ playbooks/ocp/baremetal-ocp-prepare.yml --tags dns --check
ansible-playbook -i inventory/ playbooks/ocp/baremetal-ocp-prepare.yml --tags dns
```

Add `--limit <cluster-inventory-name>` to select a cluster. API calls are delegated
to the single `dns_primary` host; no SSH connection to the cluster itself is needed.
The [VM cluster destroy playbook](../ocp/ms-ocp-destroy.yml) removes the corresponding
Technitium Primary zone under its existing `confirm_destroy=yes` guard. Deletion
requires Zones Modify and zone Delete permissions. The destroy playbook removes
the corresponding pfSense override before deleting the zone. Legacy BIND create/destroy playbooks remain
for the old VM's lifecycle and are not part of normal OCP DNS management.

## pfSense DNS Resolver overrides

Install the controller collections from the repository root before using this
workflow (the local module imports `pfsensible.core`):

```bash
ansible-galaxy collection install -r requirements.yml
```

The collection must be in the running controller's Ansible collection path;
installing it on pfSense or only in a temporary test directory is insufficient.

The DNS playbook manages the Tailscale override from `pfsense_dns_domain_overrides`
in [DNS group variables](../../inventory/group_vars/dns.yml). It also derives OCP
overrides from cluster inventory, including only zones that already exist as
enabled Technitium Primary zones. Unprovisioned clusters are skipped. Removing
an inventory entry does not delete an existing override; the OCP destroy playbook
handles removal when retiring a VM cluster.

Use the full inventory so pfSense's SSH user and the OCP cluster definitions
are available:

```bash
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags pfsense_dns --check --diff
ansible-playbook -i inventory/ playbooks/network/dns.yml --tags pfsense_dns
```

Full untagged DNS runs also manage these overrides and therefore require
`-i inventory/`. Technitium-only tags can still use `-i inventory/dns.yml`.
Tailscale DNS must be reachable from pfSense; the override does not install or
authenticate Tailscale on the router.

The [local domain-override module](../../library/pfsense_dns_domain_override.py)
uses the pinned `pfsensible.core` configuration helpers, supports check/diff mode,
and reloads Unbound only when an override changes. It manages individual plain-DNS
overrides while preserving other domains, descriptions, host overrides, and
global resolver settings. This is repository-maintained code: the collection's
general resolver module supplies defaults for unrelated settings and is not
suitable for managing just these entries. Router operations are serialized to
avoid concurrent config writes from multiple cluster hosts in the same play.

## Task tags

Use these with `ansible-playbook -i inventory/ playbooks/network/dns.yml`.
Targeted runs assume the host has already been provisioned. Tasks tagged
`always`, including platform and primary-group validation, still run.

| Tag | Scope | Credentials needed beyond SSH/sudo |
| --- | --- | --- |
| `pfsense_dns` | Tailscale and existing OCP resolver overrides on pfSense | Technitium API token and pfSense SSH access; full inventory |
| `network_addresses` | Hostname, native IPv4, VLANs, network firewall rules | None |
| `technitium_upgrade` | Install/upgrade to the pinned server version | None |
| `technitium_api_auth` | Load and validate the API token | Vault/API token; interactive bootstrap if needed |
| `technitium_config` | HTTPS, forwarders, query logs, blocking, exceptions, conditional zones, DNS tests | Vault/API and Cloudflare tokens |
| `technitium_web_tls` | Certificate issuance, native HTTPS, renewal, trusted HTTPS check | Vault/API and Cloudflare tokens |
| `technitium_query_logs` | Install/configure Query Logs (Sqlite) | Vault/API token |
| `technitium_exceptions` | Reconcile and test private allowed domains | Vault/API token |
| `technitium_allowed_test` | Test private allowed domains without configuration writes | Vault/API token |
| `technitium_forwarding` | Conditional forwarding only; skips exception tests | Vault/API token |
| `technitium_test` | Public resolution, block list, and private exception tests | Vault/API token for private tests |
| `technitium_blocklist_test` | UDP/TCP block list smoke test only | None |

The API/configuration and private exception tests target `dns_primary`. Public
resolution and block list tests target all active `dns` hosts. DNS smoke tests
and certificate issuance are skipped in check mode; configuration tasks can
still read existing settings to report drift. A check-mode run is not a
substitute for first provisioning.
