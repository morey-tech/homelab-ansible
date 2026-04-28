# Homelab Ansible

## Local Development Setup

This repo is structured for Ansible Automation Platform (AAP). Some settings that AAP manages automatically require manual setup for local development.

### Vault Password

AAP injects credentials directly. Locally, set the vault password file via environment variable:

```bash
export ANSIBLE_VAULT_PASSWORD_FILE=./vault-password.txt
```

Get the password from the `Ansible ms Vault Password` entry in Bitwarden and place it in `vault-password.txt`. Add this export to your shell profile (`.zshrc`, `.bashrc`, etc.) or use a `.envrc` file with `direnv`.

### Installing Collections

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

### Destroy Playbooks (Confirmation Required)

Destroy playbooks require explicit confirmation to prevent accidents. Pass `confirm_destroy=yes` as an extra variable:

```bash
ansible-playbook playbooks/ocp/ms-ocp-destroy.yml -e confirm_destroy=yes
ansible-playbook playbooks/lan/lan-unifi-destroy.yml -e confirm_destroy=yes
```

In AAP, add an [AAP Survey](https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/html/using_automation_execution/controller-job-templates#ug_JobTemplates_surveys) field requiring `confirm_destroy=yes` before the job runs.

### Bare-Metal OCP (Two-Stage Process)

Bare-metal OCP cluster creation requires a manual step (booting from USB). Run in two stages:

```bash
# Stage 1: Create cluster, configure DNS/DHCP, download Discovery ISO
ansible-playbook playbooks/ocp/baremetal-ocp-prepare.yml

# Write the ISO to USB, boot each node, then run stage 2:
ansible-playbook playbooks/ocp/baremetal-ocp-install.yml
```

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

The UniFi Network Controller runs on an LXC container on the LAN network.

- **Web UI**: https://192.168.1.13:8443
- **Inform URL**: http://192.168.1.13:8080/inform

### Create/Destroy

```bash
ansible-playbook playbooks/lan/lan-unifi-create.yml
ansible-playbook playbooks/lan/lan-unifi-destroy.yml -e confirm_destroy=yes
```

### Adopting Devices

SSH into the device and run the `set-inform` command (credentials for provisioned devices are `root` / `server` in Bitwarden):

```bash
ssh root@<device-ip>
set-inform http://192.168.1.13:8080/inform
```

Note: It may take 2-3 tries before the device is picked up.
