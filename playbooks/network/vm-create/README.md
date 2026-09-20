# Create dns-01 in QNAP Virtualization Station

This runbook takes a new VM through Fedora installation, SSH key access, and
passwordless sudo, ready for [the DNS playbook](../dns.yml). It reconstructs the
September 20, 2026 screenshots in this directory in execution order. Screenshot
filenames are numbered in runbook order, with all VM settings before the final
summary. Commands
below are instructions for the operator; creating the documentation does not
run them against the NAS or VM.

The screenshots use a DHCP reservation to bootstrap `192.168.1.53`. The DNS
playbook subsequently converts the guest connection to static IPv4, retaining
that address and disabling DHCP. The final gateway and host DNS resolver are
`192.168.1.1`; the old `192.168.1.17` address is not part of this setup.

## 1. Prepare the NAS, network, and installer

Use the existing QNAP NAS `qnap-01.rh-lab.morey.tech`, with Virtualization
Station installed and the `vsw-infra-trunk` virtual switch available. Its
physical connection must carry native/untagged VLAN 1 and tagged VLANs 3, 6,
and 20. The screenshots start with these NAS and switch prerequisites already
in place; they do not show their creation.

If replacing an existing VM using `.1.53`, shut down that VM before the new one
uses the address. Keep AdGuard running on `.3.53`: VLAN 3 stays disabled in the
DNS playbook until the later cutover.

Download the Fedora Server DVD ISO to the NAS. The captured installation uses
**Fedora 44**, specifically `Fedora-Server-dvd-x86_64-44-1.7.iso`. From the
controller terminal, the recorded download command is:

```bash
ssh tecno@qnap-01.rh-lab.morey.tech \
  'wget -c -O /share/storage-mass/qnap-01/virtualization-station-data/Fedora-Server-dvd-x86_64-44-1.7.iso https://download.fedoraproject.org/pub/fedora/linux/releases/44/Server/x86_64/iso/Fedora-Server-dvd-x86_64-44-1.7.iso'
```

This is the recorded release URL, not a dynamically selected latest release.
If the ISO is already present, reuse it. The QNAP file picker displays the
shared folder without the shell path's `/share` prefix.

Reference: [ISO download](01-download-fedora-iso.png).

## 2. Create the virtual machine

Open **Virtualization Station → Create Virtual Machine**. Fill in **General**:

| Setting | Value |
| --- | --- |
| VM name | `dns-01` |
| Description | Blank in the capture |
| File location | `/storage-mass/qnap-01/virtualization-station-data` |
| OS | Linux |
| OS distribution | Fedora |
| OS version/profile | Fedora 41 |

**Fedora 41 is the QNAP profile selected in the screenshots. The mounted ISO
and installed guest are Fedora 44.**

Choose **Advanced settings** under **Customize Settings**, then configure the
five pages in this order:

| Page | Settings |
| --- | --- |
| 1. System | CPU model **Passthrough**; **4 CPUs**; CPU Hot Add off; **8 GB** memory; memory sharing on; dynamic allocation on; **4 GB** reserved memory; shares **Normal (100)**; **UEFI** firmware; **Q35** machine type |
| 2. Hard disk | One **new 32 GB** image; **VirtIO** controller; **Writeback** cache; **Enable Space Reclaim** checked |
| 3. Network | One **VirtIO** adapter attached to **vsw-infra-trunk**, shown as Adapter 1+2 (5 GbE); record the final MAC address |
| 4. CD/DVD | One **SATA** CD/DVD drive with `Fedora-Server-dvd-x86_64-44-1.7.iso` mounted |
| 5. Miscellaneous | **VGA** video; audio off; **USB 3.0**; Auto Start Policy **None**; keyboard **English (US)**; VNC password off |

Review the summary, leave **Automatically start the VM after creation**
unchecked, and click **Create**. The captured auto-start policy is also off;
this runbook records the installation baseline, not a later NAS boot policy.

The early network screenshots contain different generated MAC addresses.
Use the MAC on the **created VM**, not an earlier wizard capture. The final
DHCP reservation and [inventory](../../../inventory/dns.yml) record
`52:54:00:98:84:61`. If recreation generates another MAC, update both the
reservation and inventory. The inventory's `mac_address` field records the
value; it does not configure QNAP or the DHCP server.

The wizard shows an Internet-connectivity warning while selecting the trunk
switch. Confirm that the VM actually has LAN and gateway connectivity during
installation; the warning itself is not a configuration step.

References:

- [General](02-vm-general-settings.png)
- [CPU and memory](03-vm-cpu-memory.png), [memory and firmware](04-vm-memory-uefi-q35.png)
- [Disk](05-vm-disk.png)
- [Switch selection](06-vm-select-trunk-switch.png), [network adapter](07-vm-network-adapter.png)
- [Mounted installer](08-vm-mount-fedora-iso.png), [miscellaneous](09-vm-miscellaneous-settings.png)
- [Final summary, top](10-vm-final-summary-general.png), [final summary, bottom](11-vm-final-summary-devices.png)

## 3. Reserve the bootstrap address

On the router, open **Services → DHCP Server → LAN → Static Mapping** and add
or edit the mapping for the final VM MAC:

| Setting | Value |
| --- | --- |
| MAC Address | Actual VM MAC; captured value `52:54:00:98:84:61` |
| Client Identifier | Blank |
| IP Address | `192.168.1.53` |
| Static ARP Entry | Unchecked |
| Hostname | `dns-01` |
| Description | Blank |
| Early DNS Registration | Track subnet |
| WINS Servers | Blank |
| DNS Servers | `192.168.1.1`; second entry blank |

Save and apply the mapping. As the router form states, keep this address
outside the dynamic DHCP pools. The LAN must supply the `/24` network and
`192.168.1.1` gateway. A DHCP reservation still uses a DHCP client; the first
DNS playbook run removes that dependency inside the guest.

This screenshot was taken during installation. It is placed here so the
reservation exists before the guest requests its address. If the installer
already obtained another lease, reconnect its network or reboot after saving
the mapping, then confirm it receives `.1.53`.

Reference: [LAN reservation](12-router-dhcp-reservation.png).

## 4. Install Fedora Server

Start `dns-01` and open its **Console**. Select **Install Fedora 44** from the
boot menu. The [blank console capture](13-vm-console-before-boot.png) contains no readable
settings; the next capture shows the [installer boot menu](14-fedora-boot-menu.png).

In the installer, make these selections. Use **Done** to return from each
configuration page to the installation summary.

| Installer page | Selection |
| --- | --- |
| Welcome / language | **English → English (Canada)** |
| Keyboard | **English (US)** |
| Time & Date | **Americas/Toronto**, as shown on the summary |
| Installation Source | Auto-detected DVD source |
| Software Selection | **Fedora Server Edition** |
| Additional software | **Container Management**, **Domain Membership**, **Guest Agents**, **Hardware Support for Server Systems**, and **Headless Management** checked |
| Installation Destination | Select the **32 GiB Virtio Block Device (`vda`)**; **Automatic** partitioning; reclaim-space and encryption options unchecked |
| Network & Host Name | Enable `enp1s0`; use the LAN DHCP reservation for `.1.53`; set hostname `dns-01` |
| Root Account | **Disable root account** |
| User Creation | Full name and username **morey-tech**; administrative privileges / wheel membership checked; require a password checked; enter and confirm the account password |

The network detail page was not captured. Its summary shows `enp1s0` connected,
and the later SSH session confirms hostname `dns-01` and address `.1.53`.
The hostname/address instructions above supply the required outcome rather
than transcribing an unseen network form. Keep passwords out of this runbook.

Click **Begin Installation**, wait for **Complete!**, then click **Reboot
System**. Eject the installer ISO in QNAP if needed to boot the installed disk
instead of returning to the installer.

References:

- [Language](15-fedora-language.png), [software selection](16-fedora-software-selection.png)
- [Installation destination](17-fedora-installation-disk.png), [root account](18-fedora-disable-root.png)
- [Administrator user](19-fedora-create-admin-user.png), [installation summary](20-fedora-installation-summary.png)
- [Installation complete](21-fedora-installation-complete.png)

## 5. Configure SSH keys and passwordless sudo

Run controller commands from the environment that will run Ansible, normally
the devcontainer. Its SSH key or forwarded SSH agent must be available there.
The capture connects through `dns-01.home.morey.tech`; use `192.168.1.53`
instead if hostname resolution is not yet available.

First confirm password login, then return to the controller:

```bash
ssh morey-tech@dns-01.home.morey.tech
exit
```

Install the controller's public key and log in again:

```bash
ssh-copy-id morey-tech@dns-01.home.morey.tech
ssh morey-tech@dns-01.home.morey.tech
```

The captured `ssh-copy-id` uses a key from `ssh-add -L` and reports one key
added. If you need to select a specific key, supply its public key file with
`ssh-copy-id -i /path/to/key.pub`. The second login should not request the
VM account password.

Inside the VM, configure the passwordless sudo rule shown in the capture:

```bash
echo 'morey-tech ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/morey-tech >/dev/null
sudo chmod 0440 /etc/sudoers.d/morey-tech
sudo visudo -cf /etc/sudoers.d/morey-tech
```

Enter the account password for the initial sudo prompt. Require `parsed OK`
from `visudo`. Verify without relying on cached sudo authentication, then
return to the controller:

```bash
sudo -k
sudo -n id -u
exit
```

Expected output is `0`. This grants the automation user passwordless root
privileges, allowing the playbook to run without `--ask-become-pass`.

Reference: [SSH, key installation, and sudo setup](22-ssh-key-and-passwordless-sudo.png).

## 6. Verify Ansible access

From `/workspaces/homelab-ansible`, confirm
[inventory/dns.yml](../../../inventory/dns.yml) uses `192.168.1.53` and
`morey-tech`. Check that [dns-01 host variables](../../../inventory/host_vars/dns-01.yml)
match the guest's interface and connection profile. To inspect them remotely:

```bash
ssh morey-tech@192.168.1.53 'nmcli -f NAME,DEVICE connection show --active'
```

The playbook currently expects `enp1s0` and `Wired connection 1`. If the
installer creates a different profile name, update `dns_native_connection`
before running the playbook.

Prepare the local controller as described in the
[repository setup](../../../README.md#local-development-setup), including the
untracked `vault-password.txt` and required Ansible collections. Then run:

```bash
ansible -i inventory/dns.yml dns-01 -m ansible.builtin.ping
ansible -i inventory/dns.yml dns-01 --become -m ansible.builtin.command -a 'id -u'
```

Require `SUCCESS` with `"ping": "pong"`, followed by successful privilege
escalation returning `0`. The first command checks SSH and Python execution;
the second also checks the sudo configuration. The captured `ansible -m ping
dns-01` succeeds with Python 3.14. Explicit inventory selection above keeps
this check limited to the DNS inventory.

Reference: [Successful Ansible ping](23-ansible-ping-success.png).

## 7. Save the baseline and hand over to the playbook

Before provisioning Technitium, open **Virtualization Station → dns-01 →
Snapshots**. Enter snapshot name **baseline**, leave the description blank,
enable **Reserve snapshot**, and click **Take Snapshot**. Wait for the
background task to finish. The captures show its creation in progress, not
completion.

References: [Baseline snapshot settings](24-qnap-baseline-snapshot.png),
[snapshot task](25-qnap-snapshot-in-progress.png).

The VM is now ready for the playbook. From the repository root:

```bash
ansible-playbook -i inventory/dns.yml playbooks/network/dns.yml
```

The playbook sets the hostname and static native IPv4 address, configures the
tagged VLANs, installs Technitium, and manages DNS configuration. VLAN 3 remains
disabled while `dns_cutover_enabled: false`. The reserved `.1.53` bootstrap
address remains the management address after DHCP is disabled.

On a new installation, follow the playbook's pause instructions to change the
Technitium admin password, create the **homelab-ansible** API token, and save
it with `ansible-vault edit`. See
[Technitium configuration as code](../README.md#technitium-configuration-as-code)
for that subsequent workflow. Do not restore a baseline snapshot expecting it
to contain later Technitium configuration.
