# Homelab Ansible

## Local Development Setup

This repo is structured for Ansible Automation Platform (AAP). Some settings that AAP manages automatically require manual setup for local development.

### Vault Password

Local runs from the repository use `vault-password.txt` automatically through
`ansible.cfg`; `--vault-password-file=vault-password.txt` is no longer necessary.
An environment variable or explicit CLI option can override this default:

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=./vault-password.txt
```

Get the password from the `Ansible ms Vault Password` entry in Bitwarden and place it in `vault-password.txt`. Keep this file untracked. In AAP, attach a Vault credential and override the local
password-file setting with the injected credential path as appropriate for the execution environment.

### Installing Collections

The Assisted Installer modules also require `requests` in the Python environment
running Ansible. The AAP execution environment includes it; install it for local
runs as well:

```bash
python3 -m pip install requests
```

```bash
ansible-galaxy collection install -r requirements.yml
```

### Running Playbooks

Playbooks are organized under `playbooks/<domain>/`:

```bash
ansible-playbook playbooks/proxmox/ms-create-vm.yml
ansible-playbook playbooks/lab/alloy-install.yml
ansible-playbook playbooks/ocp/ms-ocp-create.yml
```

### DNS and Technitium

See the [DNS playbook guide](playbooks/network/README.md) for provisioning,
upgrades, VLAN addressing, encrypted credentials, HTTPS, DNS configuration,
and verification. Start with the
[QNAP VM creation runbook](playbooks/network/vm-create/README.md) when creating
or recreating `dns-01`.

### Destroy Playbooks (Confirmation Required)

Destroy playbooks require explicit confirmation to prevent accidents. Pass `confirm_destroy=yes` as an extra variable:

```bash
ansible-playbook playbooks/ocp/ms-ocp-destroy.yml -e confirm_destroy=yes
ansible-playbook playbooks/lan/lan-unifi-destroy.yml -e confirm_destroy=yes
```

In AAP, add an [AAP Survey](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/html/using_automation_execution/controller-job-templates#ug_JobTemplates_surveys) field requiring `confirm_destroy=yes` before the job runs.

### Bare-Metal OCP (Two-Stage Process)

The bare-metal playbooks default to `ocp-mgmt.rh-lab.morey.tech`, replacing the
old management SNO and standalone GPU cluster with this layout from
[homelab #187](https://github.com/morey-tech/homelab/issues/187):

| Physical node | Node address | Role |
| --- | --- | --- |
| `ms-02` / Desktop Nick | `192.168.6.91` | Schedulable control plane |
| `ms-03` | `192.168.6.92` | Schedulable control plane |
| `ms-04` | `192.168.6.93` | Schedulable control plane |
| `tr-gpu` | `192.168.6.94` | Worker |

The API VIP is `192.168.6.90`; ingress uses `192.168.6.98`. Node DNS names are
`<physical-node>.ocp-mgmt.rh-lab.morey.tech`. Inventory requests the `4.22`
stream; Assisted Installer must offer that version when preparing the cluster.
The existing `ocp-home` SNO on `ms-01` retains its inventory settings. To target
another bare-metal cluster explicitly, pass `-e baremetal_cluster=<inventory-host>`.

Before preparing, remove conflicting old DNS/DHCP/static assignments and exclude
`.90`–`.98` from dynamic DHCP. Each node uses a two-port 10GbE LACP bond
with MTU 1500 on the untagged RH lab network (VLAN 6 on the switch). Configure
the switch LAGs and validate that network before booting the ISO. The ISO maps
logical NIC names to the permanent MAC addresses in `inventory/rh-lab.yml`;
bond slaves can show the same current MAC while running. On the three MS nodes,
the same mapping explicitly disables the two unused 2.5GbE interfaces so they
cannot obtain native-LAN IPv4 or IPv6 addresses alongside the cluster bond.

Run in two stages, with a manual USB boot between them. Provide the Red Hat
offline token and pull secret via AAP credentials or the repository Vault file
for local execution:

```bash
# Offline inventory validation and ISO network rendering only
ansible-playbook playbooks/ocp/baremetal-ocp-prepare.yml --tags preflight

# Stage 1: Create cluster, configure DNS/DHCP, download Discovery ISO
ansible-playbook playbooks/ocp/baremetal-ocp-prepare.yml -e @group_vars/all/vault.yml
```

If an old `ocp-mgmt` installer record still exists, inspect it first and rerun
stage 1 with `-e recreate=true` to replace that record. Existing records with a
different version or topology are rejected rather than silently reused.

The `ocp-mgmt` inventory requests a `minimal-iso`; each host therefore needs
working network and DNS while booting so it can download the RHCOS rootfs. The
ISO downloads to `var/<cluster-name>-<cluster-id>-discovery.iso` in the
repository. That directory is gitignored and bind-mounted to the laptop when
using the devcontainer, so the host can read the image directly. Override
`discovery_iso_host` and `discovery_iso_directory` to save it on another
persistent, reachable host when using AAP. Desktop Nick is now a cluster node
and is no longer the download destination.

Write the ISO to USB and boot all four machines. In Assisted Installer's
discovered hardware inventory, identify each intended 500 GB OS disk by its
model/serial and copy its exact disk `id` into that node's
`installation_disk_id` in `inventory/rh-lab.yml`. The current four IDs were
recorded from discovered hardware; do not substitute an assumed `/dev/nvme0n1`
path. Keep the 2 TB data, model-cache, and scratch disks separate.

```bash
# Stage 2: Match hardware, assign roles and OS disks, then install
ansible-playbook playbooks/ocp/baremetal-ocp-install.yml -e @group_vars/all/vault.yml
```

Stage 2 matches each machine by its configured bond MAC, assigns the three
MS nodes as masters and `tr-gpu` as a worker, and gives each node a distinct
`topology.kubernetes.io/zone` label. It selects only the specified OS disk and
marks the other discovered disks to skip formatting. It checks the resulting
host assignments and cluster readiness before starting installation. If discovery
or readiness takes longer than four minutes, inspect Assisted Installer's
validation messages and rerun stage 2 after resolving them.

GPU operators, GPU workload placement, and Intel-only KubeVirt placement are
subsequent cluster configuration steps.

### Execution Environment (EE)

The EE image is built automatically via GitHub Actions when `execution-environment.yml` or `ee-requirements.yml` change. The image is published to `ghcr.io/nmorey/homelab-ansible/ee-homelab`.

To build locally:

```bash
pip install ansible-builder
ansible-builder build -f execution-environment.yml -t homelab-ee:latest
```

---

## Renovate PR Workflow

Renovate creates PRs for Ansible Galaxy collection updates in `requirements.yml` and `ee-requirements.yml`. Follow this workflow to test and merge them safely.

### 1. Review Breaking Changes

Check the PR description for release notes and breaking changes:

```bash
gh pr view <PR_NUMBER> --json body -q .body
```

Key things to check:
- **Version requirements** (e.g., pfSense 2.8.0+ for pfsensible.core 0.7.0+)
- **Removed/relocated modules** (e.g., Proxmox modules moved to community.proxmox in community.general 11.0.0)
- **Behavior changes** in modules you use

### 2. Identify Used Modules

Find which modules from the collection are used in playbooks:

```bash
grep -r "collection_name\." playbooks/ --include="*.yml"
```

### 3. Checkout and Rebase

```bash
gh pr checkout <PR_NUMBER>
git fetch origin main && git rebase origin/main
```

### 4. Install Updated Collections

```bash
ansible-galaxy collection install -r requirements.yml --force
```

### 5. Test Playbooks

Run syntax checks on affected playbooks:

```bash
ansible-playbook --syntax-check playbooks/<domain>/<playbook>.yml
```

Run actual playbooks to test functionality:

```bash
ansible-playbook playbooks/<domain>/<playbook>.yml
```

### 6. Comment and Merge

```bash
gh pr comment <PR_NUMBER> --body "## Testing Results
- Environment: <versions>
- Tested: <playbooks>
- Results: <pass/fail details>"

git push --force-with-lease
gh pr merge <PR_NUMBER> --squash --delete-branch
```

### Handling Breaking Changes

For major changes like module relocations:

1. Add new collection to `requirements.yml` and `ee-requirements.yml`
2. Update module FQCNs in all playbooks (e.g., `community.general.proxmox` → `community.proxmox.proxmox`)
3. Run syntax checks on all modified files
4. Test with actual playbook execution
5. Commit fixes to the PR branch before merging

---

## Initial Configuration

Ensure SSH key authentication is configured for all hosts:

```bash
ssh-copy-id root@ms-04.home.morey.tech
```

Confirm with the `ping` module:

```bash
ansible -m ping pvems-nodes
```

## Setting Up Proxmox API Permissions

Create a new user named `ansible` with the Realm `Proxmox VE` on the Proxmox datacenter.
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::14

Assign `PVEAdmin` role and path `/` to the `ansible@pve` user and the `ansible@pve!ansible` token.
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::6

Create an API token with the Token ID `ansible`.
- https://ms-04.home.morey.tech:8006/#v1:0:18:4:31::::::=apitokens

## Upgrading Proxmox Nodes

```bash
ansible-playbook playbooks/proxmox/pvems-upgrade.yml
```

## UniFi Network Controller

UniFi OS Server runs on the dedicated Ubuntu VM `unifi` on QNAP.

- **Web UI**: https://unifi.home.morey.tech:11443
- **Inform URL**: http://192.168.1.13:8080/inform

### Provision and verify

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_ready
```

See the [UniFi runbook](playbooks/lan/README.md) for VM preparation, firewall
configuration, and maintenance.

Configure VM-local Certbot issuance and renewal for the console:

```bash
ansible-playbook -i inventory/ playbooks/lan/unifi-os.yml --tags unifi_web_tls
```

### Adopting Devices

SSH into the device and run the `set-inform` command (credentials for provisioned devices are `root` / `server` in Bitwarden):

```bash
ssh root@<device-ip>
set-inform http://192.168.1.13:8080/inform
```

Note: It may take 2-3 tries before the device is picked up.
