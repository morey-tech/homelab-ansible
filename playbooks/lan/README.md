# UniFi on QNAP

The replacement UniFi host will be a new VM on `qnap-01`, restored from the
existing Network application 8.6.9 backup. Its final address will be
`192.168.1.13/24`. Use a separate, confirmed available address during setup;
do not assign the final address while the old controller still owns it.

The existing [create playbook](lan-unifi-create.yml) provisions a **Proxmox LXC**.
It is not the QNAP VM provisioning workflow. The existing
[destroy playbook](lan-unifi-destroy.yml) also targets that LXC and removes its
DHCP reservation; do not use it to clean up the old controller after transferring
the reservation without reviewing that behavior.

## VM preparation

Create a fresh VM in QNAP Virtualization Station. The
[DNS VM runbook](../network/vm-create/README.md) illustrates this NAS's wizard,
storage location, console, SSH key setup, and baseline snapshots. Its Fedora
installer, DNS addresses, MAC address, and tagged VLAN configuration are specific
to DNS and should not be copied into the UniFi VM.

For this VM, use native/untagged VLAN 1, a newly generated MAC, and a temporary
LAN address. A starting allocation is 2 vCPUs, 4 GiB RAM, and a 64 GiB disk;
increase storage for longer statistics retention. Record the actual MAC,
interface name, bootstrap IP, and SSH user before preparing inventory.

Use Ubuntu Server 24.04 and the official UniFi OS Server installer, following
[Ubiquiti's self-hosting requirements and installation guide](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi).
The guest hostname is `unifi` and its administrative user is `morey-tech`.

Enable SSH, install the Ansible controller's public key, verify Python and
passwordless sudo, and take a baseline snapshot before installing UniFi.

## Install UniFi OS Server with Ansible

Confirm the temporary address in [inventory/unifi.yml](../../inventory/unifi.yml)
matches the new VM. The distinct `unifi.home.morey.tech` inventory entry still
represents the legacy LXC at `.13`.

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

Open `https://TEMP_IP:11443` to complete setup. The initial certificate is
self-signed. Restore the Network `.unf` backup through the UI and inspect the
imported configuration. Application restore and initial account setup are manual;
the playbook does not read or upload the backup. Configure the web port before
the first installation; changing its variable later does not migrate the service.

`unifi_staging: true` keeps device inform, STUN, discovery, and other declared
device ports blocked in both directions, including outbound adoption SSH. SSH
administration and the console stay available, while ordinary outbound Internet
access remains enabled for installation. UFW rules cover IPv4 and IPv6 using
Ubuntu's default UFW configuration. Devices should remain offline in the new
console during this inspection. Avoid device adoption, provisioning, firmware
updates, and Site Magic configuration until cutover. The playbook checks console
HTTPS access and that TCP 8080 is unreachable from the Ansible controller; this
does not exercise every UDP rule or prove isolation from every network segment.

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

Check mode is useful on a provisioned host. It cannot validate installation or
new firewall rules before the prerequisite packages exist.

## Restore and cutover

Keep the original backup outside tracked files (the repository's `/var/`
directory is ignored). Record its path and backup type without committing its
contents. Version 8.6.9 identifies the source; choose and verify the destination
release before installation. Use Ubiquiti's supported
[backup restore workflow](https://help.ui.com/hc/en-us/articles/360008976393-Backups-and-Migration-in-UniFi).

1. Provision and verify the new guest at its temporary address.
2. Install the selected UniFi platform and restore the Network backup through
   its UI. During staging, isolate the replacement from managed devices so it
   cannot take over or provision devices before cutover. Preserve administrative
   access for checking the restored sites, networks, and device inventory.
3. At cutover, take a fresh backup if the source configuration has changed,
   restore it as needed, then stop the old controller and disable its autostart.
4. Transfer any LAN reservation to the new VM's MAC and configure the guest's
   final address, prefix, gateway, and DNS. Remove its temporary address and
   verify `unifi.home.morey.tech` resolves to the final address.
5. Restore device connectivity to the replacement. Verify the restored inform
   host setting uses the intended final address or hostname. Check devices
   reconnect, sites and networks are correct, and Wi-Fi/client traffic works.
6. Verify web TLS and automatic certificate renewal for the selected platform,
   then enable VM autostart and take a post-restore backup.

Retain the old VM/container stopped for rollback. To roll back, stop the new
controller before returning the IP/reservation to the old one. Do not let both
controllers claim the final address.

After stopping the old LXC and transferring the final address, update
`ansible_host` to `192.168.1.13` and set `unifi_staging: false` in host variables.
Rerun `playbooks/lan/unifi-os.yml` to open the declared device ports and remove
the staging egress blocks. The playbook refuses production mode at a temporary
address, but does not stop the old LXC, change DHCP, or perform the IP cutover.

On an already provisioned VM, apply only the firewall changes and test TCP 8080:

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_firewall
```

UFW skips inserting a rule if the same port already has the opposite action,
so the tasks remove the obsolete rule before inserting its replacement. The
connectivity check requires port 8080 to be blocked during staging and reachable
after cutover. Ping and HTTPS access alone do not verify device inform access.
