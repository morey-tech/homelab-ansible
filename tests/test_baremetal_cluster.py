"""Offline checks for physical host identity, OS disk selection and ISO networking."""
import copy
import importlib.util
import json
from pathlib import Path
import unittest

from ansible.errors import AnsibleFilterError
from jinja2 import Environment
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "baremetal_hosts", ROOT / "playbooks/ocp/filter_plugins/baremetal_hosts.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BaremetalClusterTest(unittest.TestCase):
    def setUp(self):
        self.inventory = yaml.safe_load((ROOT / "inventory/rh-lab.yml").read_text())
        self.nodes = []
        self.hosts = []
        for index, (name, config) in enumerate(self.inventory["ocp-mgmt-nodes"]["hosts"].items()):
            node = dict(config, inventory_hostname_short=name.split(".")[0],
                        installation_disk_id=f"/dev/disk/by-id/os-{index}")
            self.nodes.append(node)
            self.hosts.append({
                "id": f"host-{index}", "infra_env_id": "infra-env",
                "role": node["node_role"], "requested_hostname": node["inventory_hostname_short"],
                "installation_disk_id": node["installation_disk_id"],
                "inventory": json.dumps({
                    "interfaces": [{"mac_address": node["mac_address"].upper()}] * 3,
                    "disks": [
                        {"id": node["installation_disk_id"], "installation_eligibility": {"eligible": True}},
                        {"id": f"/dev/disk/by-id/data-{index}", "installation_eligibility": {"eligible": True}},
                    ],
                }),
            })

    def test_shuffled_discovery_and_shared_bond_mac_match_the_correct_physical_nodes(self):
        plan = MODULE.baremetal_host_plan(list(reversed(self.hosts)), self.nodes, verify=True)
        self.assertEqual([item["id"] for item in plan], [f"host-{i}" for i in range(4)])
        self.assertEqual([item["body"]["host_role"] for item in plan], ["master"] * 3 + ["worker"])
        for item in plan:
            skipped = item["body"]["disks_skip_formatting"]
            self.assertFalse(skipped[0]["skip_formatting"])
            self.assertTrue(skipped[1]["skip_formatting"])

    def test_unknown_extra_missing_and_duplicate_hosts_are_rejected(self):
        for hosts in (self.hosts[:-1], self.hosts + [self.hosts[0]], [self.hosts[0]] * 4):
            with self.subTest(hosts=len(hosts)), self.assertRaises(AnsibleFilterError):
                MODULE.baremetal_host_plan(hosts, self.nodes)
        hosts = copy.deepcopy(self.hosts)
        hosts[-1]["inventory"] = json.dumps({"interfaces": [{"mac_address": "00:00:00:00:00:00"}]})
        with self.assertRaises(AnsibleFilterError):
            MODULE.baremetal_host_plan(hosts, self.nodes)

    def test_no_disk_autoselection(self):
        for disk in ("", "/dev/nvme0n1", "/dev/disk/by-id/missing"):
            nodes = copy.deepcopy(self.nodes)
            nodes[-1]["installation_disk_id"] = disk
            with self.subTest(disk=disk), self.assertRaises(AnsibleFilterError):
                MODULE.baremetal_host_plan(self.hosts, nodes)

    def test_ineligible_disk_and_installation_media_are_rejected(self):
        for change in ({"removable": True}, {"is_installation_media": True},
                       {"installation_eligibility": {"eligible": False}}):
            hosts = copy.deepcopy(self.hosts)
            inventory = json.loads(hosts[0]["inventory"])
            inventory["disks"][0].update(change)
            hosts[0]["inventory"] = json.dumps(inventory)
            with self.subTest(change=change), self.assertRaises(AnsibleFilterError):
                MODULE.baremetal_host_plan(hosts, self.nodes)

    def test_final_role_hostname_and_disk_must_match(self):
        for key, value in (("role", "master"), ("requested_hostname", "wrong"),
                           ("installation_disk_id", "/dev/disk/by-id/wrong")):
            hosts = copy.deepcopy(self.hosts)
            hosts[-1][key] = value
            with self.subTest(key=key), self.assertRaises(AnsibleFilterError):
                MODULE.baremetal_host_plan(hosts, self.nodes, verify=True)

    def test_iso_has_four_distinct_networks_and_mac_maps(self):
        env = Environment()
        env.filters.update(to_json=json.dumps, to_nice_yaml=yaml.safe_dump)
        template = env.from_string((ROOT / "playbooks/ocp/templates/baremetal-static-network.json.j2").read_text())
        variables = dict(self.inventory["rh-lab"]["vars"])
        variables.update(self.inventory["baremetal-ocp-clusters"]["hosts"]["ocp-mgmt.rh-lab.morey.tech"])
        variables.update(groups={"ocp-mgmt-nodes": list(self.inventory["ocp-mgmt-nodes"]["hosts"])},
                         hostvars=self.inventory["ocp-mgmt-nodes"]["hosts"])
        configs = json.loads(template.render(**variables))
        self.assertEqual(len(configs), 4)
        for index, config in enumerate(configs):
            network = yaml.safe_load(config["network_yaml"])
            bond = network["interfaces"][0]
            self.assertEqual(bond["ipv4"]["address"][0]["ip"], f"192.168.6.{91 + index}")
            self.assertEqual(bond["mac-address"], self.nodes[index]["mac_address"])
            self.assertEqual(bond["link-aggregation"]["mode"], "802.3ad")
            self.assertEqual([nic["mac_address"] for nic in config["mac_interface_map"]],
                             self.nodes[index]["bond_mac_addresses"]
                             + self.nodes[index]["disabled_interface_mac_addresses"])
            disabled = network["interfaces"][1:]
            self.assertEqual(len(disabled), 2 if self.nodes[index]["node_role"] == "master" else 0)
            for interface in disabled:
                self.assertEqual(interface["state"], "down")
                self.assertFalse(interface["ipv4"]["enabled"])
                self.assertFalse(interface["ipv6"]["enabled"])


if __name__ == "__main__":
    unittest.main()
