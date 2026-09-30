# UniFi on QNAP

UniFi OS Server runs on the Ubuntu VM `unifi` on `qnap-01` at
`192.168.1.13/24`, with gateway `192.168.1.1`. The console is available at
https://unifi.home.morey.tech:11443 and devices use
`http://192.168.1.13:8080/inform`.

The older `lan-unifi-create.yml` and `lan-unifi-destroy.yml` playbooks manage
a Proxmox LXC, not this VM. The destroy playbook also removes its DHCP
reservation; those playbooks are not part of this VM’s maintenance workflow.

## VM preparation

Create a fresh VM in QNAP Virtualization Station. The
[DNS VM runbook](../network/vm-create/README.md) illustrates this NAS's wizard,
storage location, console, SSH key setup, and baseline snapshots. Its Fedora
installer, DNS addresses, MAC address, and tagged VLAN configuration are specific
to DNS and should not be copied into the UniFi VM.

For this VM, use native/untagged VLAN 1 and a DHCP reservation for its MAC.
A starting allocation is 2 vCPUs, 4 GiB RAM, and a 64 GiB disk;
increase storage for longer statistics retention. Record the actual MAC,
interface name, IP address, and SSH user in inventory as appropriate.

Use Ubuntu Server 24.04 and the official UniFi OS Server installer, following
[Ubiquiti's self-hosting requirements and installation guide](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi).
The guest hostname is `unifi` and its administrative user is `morey-tech`.

Enable SSH, install the Ansible controller's public key, verify Python and
passwordless sudo, and take a baseline snapshot before installing UniFi.

## Install UniFi OS Server with Ansible

[Inventory](../../inventory/unifi.yml) targets `192.168.1.13` as `morey-tech`.

From the repository root:

```bash
ansible-galaxy collection install -r requirements.yml
ansible -i inventory/ unifi -m ansible.builtin.ping
ansible -i inventory/ unifi --become -m ansible.builtin.command -a 'id -u'
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --syntax-check
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml
```

The [playbook](unifi-os.yml) targets only `unifi`. It installs the Ubuntu Podman,
Pasta, and slirp4netns prerequisites, configures UFW, and runs the official
installer noninteractively. [Host variables](../../inventory/host_vars/unifi.yml)
pin the initial OS Server release to
[5.1.42](https://community.ui.com/releases/UniFi-OS-Server-5-1-42/509f4de9-8fe4-4718-abad-1bb6990dedcc),
which bundles Network 10.5.67. The SHA-256 records the bytes downloaded from
Ubiquiti over HTTPS; it is not an independently published vendor signature.
Ansible enables the vendor's `uosserver` service without defining containers or
replacing its service units. When that service already exists, installation is
skipped; subsequent upgrades are managed through UniFi's Update Manager. Changing
the initial version pin does not upgrade an existing installation. A partially
failed installation needs inspection before rerunning; do not force a reinstall
over restored data.

Open `https://unifi.home.morey.tech:11443` to access the console. Before certificate
provisioning, the IP URL uses a self-signed certificate. Restore a Network `.unf`
backup through the UI and inspect the
imported configuration. Application restore and initial account setup are manual;
the playbook does not read or upload the backup. Configure the web port before
the first installation; changing its variable later does not migrate the service.

UFW permits SSH, console HTTPS, and the declared device ports, denies other
unsolicited inbound traffic, and permits outbound traffic. Rules cover IPv4 and
IPv6 using Ubuntu’s default UFW configuration. The playbook checks console HTTPS
and TCP 8080 from the Ansible controller; it does not test every UDP port or
connectivity from every device network.

Readiness also polls `/api/system` until its JSON `deviceState` is `notSetup`
(ready for initial setup) or `setup` (configured). The HTTPS page alone can return
200 while its JavaScript displays the boot screen. The state check retries 60
times at 10-second intervals, with a 10-second timeout per request, and rejects
missing/unknown states and HTML responses. It waits for OS readiness, not backup
restore completion or all Network devices becoming online. Recheck without
running provisioning tasks:

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_ready
```

The firewall port list covers core Network management. Add feature-specific
ports, such as guest portals, only if used, consulting the
[official port reference](https://help.ui.com/hc/en-us/articles/218506997-Required-Ports-Reference).
Do not expose the internal database port. The legacy Java-keystore certificate
scripts are not part of this installation; use UniFi OS's certificate settings.

## Automatic console certificates

The `unifi_web_tls` tasks install Ubuntu's Certbot and Cloudflare DNS plugin on
the VM. DNS-01 validation obtains a Let's Encrypt certificate for
`unifi.home.morey.tech`; no inbound Internet access or port 80 rule is needed.
Local DNS must resolve that name to `192.168.1.13`. A certificate for this name
does not validate access by IP address.

The existing `cloudflare_dns_edit_api_token` variable in
`group_vars/all/vault.yml` supplies the Cloudflare credential. Keep it encrypted
with Ansible Vault, or inject it through an AAP credential. The token needs
Zone:DNS:Edit access for `morey.tech`, following the
[Certbot plugin documentation](https://certbot-dns-cloudflare.readthedocs.io/en/stable/).
Ansible writes it to `/etc/letsencrypt/unifi-cloudflare.ini` with mode `0600`
and suppresses its value in logs and diffs.

Run certificate setup independently on the provisioned VM:

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_web_tls
```

The root-owned deploy hook at
`/etc/letsencrypt/renewal-hooks/deploy/unifi-os` imports the full chain and private
key through the container-local `/api/userCertificates` IPC API, then activates
the certificate. UniFi manages storage, its certificate records, and the nginx
reload. The hook leaves the vendor's internal identity certificates untouched
and does not restart the Network application or the container. It uses local
Podman access as `uosserver`; no UI password or session token is stored.

This is an **internal API**, verified by inspecting the installed UniFi OS Server
5.1.42 code and querying its certificate-list endpoint. It is not a documented,
stable Ubiquiti API. The playbook checks it before issuance. Recheck compatibility
after OS upgrades; unsupported responses cause the hook to fail instead of
editing certificate files directly.

The hook checks certificate trust, hostname, expiry, and key matching before
import. After activation it verifies the certificate served on the console port
using the domain as TLS SNI. If activation or that verification fails, it attempts
to restore the previous certificate selection and reports failure. Prior custom
certificates remain in UniFi for recovery and can be removed manually once no
longer needed. Re-running the hook with the same active certificate verifies it
without importing or activating it again. Ansible also verifies trusted HTTPS
through the domain from the controller.

`certbot.timer` handles automatic renewal on the VM, independently of Ansible.
Certbot runs the deploy hook after successful issuance or renewal. Rerunning the
TLS tasks also retries deployment if renewal succeeded but a previous hook failed.
Changing the configured domain creates a new lineage; remove obsolete lineages
separately with Certbot once they are no longer used. Setting
`unifi_web_tls_enabled: false` skips configuration; it does not uninstall renewal
or remove an active certificate.

After initial setup, test renewal and deployment on the VM:

```bash
sudo certbot renew --cert-name unifi.home.morey.tech --dry-run --run-deploy-hooks
sudo systemctl status certbot.timer
sudo journalctl -u certbot.service
```

With `--run-deploy-hooks`, the dry run deploys the current live certificate, not
the untrusted staging certificate. See the
[Certbot renewal guide](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates).
Inspect timer logs for renewal or hook failures. To retry deployment alone:

```bash
sudo /etc/letsencrypt/renewal-hooks/deploy/unifi-os
```

Check mode is useful on a provisioned host. It cannot validate installation or
new firewall rules before the prerequisite packages exist.

## Firewall maintenance

On an already provisioned VM, apply only the firewall changes and test TCP 8080:

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_firewall
```

Ping and HTTPS access alone do not verify device inform access. If devices are
offline, check TCP 8080 connectivity and their inform URL. See the
[device SSH and adoption instructions](../../README.md#adopting-devices).

## Backups and recovery

Manage backups and restore through the UniFi console using the
[official backup workflow](https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi).
Keep backup contents outside tracked files; the repository’s `/var/` directory
is ignored. Validate device connectivity, Wi-Fi, and VLAN operation after a
restore or upgrade. Configure VM autostart in QNAP and verify service recovery
after a reboot. Manage TLS certificates through UniFi OS’s certificate settings.
