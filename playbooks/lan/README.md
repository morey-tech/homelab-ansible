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
LAN address. A starting allocation is 2 vCPUs, 4 GiB RAM, and a 32 GiB disk;
increase storage for longer statistics retention. Record the actual MAC,
interface name, bootstrap IP, and SSH user before preparing inventory.

Select the UniFi hosting platform before choosing the guest installer:

- UniFi OS Server: Ubuntu Server 24.04 is a supported guest option. Follow
  [Ubiquiti's self-hosting requirements and installation guide](https://help.ui.com/hc/en-us/articles/34210126298775-Self-Hosting-UniFi).
- Standalone Network Server: follow the
  [Linux installation guide](https://help.ui.com/hc/en-us/articles/220066768-Updating-and-Installing-Self-Hosted-UniFi-Network-Servers-Linux)
  and verify the chosen application's Java/MongoDB compatibility.

Enable SSH, install the Ansible controller's public key, verify Python and
passwordless sudo, and take a baseline snapshot before installing UniFi.

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

The destination platform, temporary IP, backup location, and NAS access must be
resolved before the installation and restore can be executed.
