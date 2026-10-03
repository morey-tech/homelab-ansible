"""Match discovered machines and OS disks before changing installer settings."""
import json

from ansible.errors import AnsibleFilterError


def baremetal_host_plan(discovered, nodes, verify=False):
    if len(discovered) != len(nodes):
        raise AnsibleFilterError("Discovered host count differs from inventory")
    plan = []
    matched = set()
    for node in nodes:
        name = node["inventory_hostname_short"]
        # An active bond can report the primary MAC on both slave interfaces.
        # The ISO explicitly assigns this unique inventory MAC to bond0.
        expected_mac = node["mac_address"].lower()
        candidates = []
        for host in discovered:
            inventory = json.loads(host.get("inventory") or "{}")
            macs = {nic.get("mac_address", "").lower()
                    for nic in inventory.get("interfaces", [])}
            if expected_mac in macs:
                candidates.append((host, inventory))
        if len(candidates) != 1:
            raise AnsibleFilterError(f"{name}: expected exactly one host with the configured bond MAC")
        host, inventory = candidates[0]
        if host["id"] in matched:
            raise AnsibleFilterError(f"{name}: machine already matched another inventory node")
        matched.add(host["id"])
        disk_id = node.get("installation_disk_id")
        disks = inventory.get("disks", [])
        selected = [disk for disk in disks if disk.get("id") == disk_id and disk_id]
        if len(selected) != 1:
            raise AnsibleFilterError(f"{name}: set installation_disk_id to the intended OS disk's Assisted Installer ID")
        disk = selected[0]
        if (disk.get("is_installation_media") or disk.get("removable")
                or not disk.get("installation_eligibility", {}).get("eligible", False)):
            raise AnsibleFilterError(f"{name}: selected OS disk is not eligible for installation")
        role = node["node_role"]
        if role not in ("master", "worker"):
            raise AnsibleFilterError(f"{name}: unsupported node role {role}")
        body = {
            "host_name": name,
            "host_role": role,
            "disks_selected_config": [{"id": disk_id, "role": "install"}],
            "disks_skip_formatting": [
                {"disk_id": other["id"], "skip_formatting": other["id"] != disk_id}
                for other in disks if other.get("id") and not other.get("is_installation_media")
            ],
            "node_labels": [{"key": "topology.kubernetes.io/zone", "value": name}],
        }
        if verify and (host.get("requested_hostname") != name
                       or host.get("role") != role
                       or host.get("installation_disk_id") != disk_id):
            raise AnsibleFilterError(f"{name}: discovered hostname, role or OS disk differs from inventory")
        plan.append({"name": name, "id": host["id"], "infra_env_id": host["infra_env_id"], "body": body})
    return plan


class FilterModule:
    def filters(self):
        return {"baremetal_host_plan": baremetal_host_plan}
