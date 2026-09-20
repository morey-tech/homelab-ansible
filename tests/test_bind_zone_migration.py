"""Offline checks for the migration reader and record comparison rendering."""
import copy
import importlib.util
from pathlib import Path
import unittest

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("read_bind_zone", ROOT / "playbooks/network/files/read-bind-zone.py")
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)
ZONE = "cluster.example.org"
SOA = f"{ZONE}. 300 IN SOA ns.{ZONE}. admin.{ZONE}. 42 3600 600 604800 300"
TRANSFER = "\n".join([
    SOA,
    f"{ZONE}. 300 IN NS ns.{ZONE}.",
    f"ns.{ZONE}. 300 IN A 192.0.2.100",
    f"api.{ZONE}. 600 IN A 192.0.2.10",
    f"*.apps.{ZONE}. 600 IN A 192.0.2.11",
    SOA,
])


class MigrationTest(unittest.TestCase):
    def parse(self, text=TRANSFER):
        return READER.parse_zone(text, ZONE, "192.0.2.100", "192.0.2.53")

    def test_preserves_application_records_and_replaces_only_nameserver_address(self):
        result = self.parse()
        self.assertEqual(result["source_zone_file"], TRANSFER)
        self.assertEqual(len(result["records"]), 5)
        addresses = {r["name"]: r["rData"]["ipAddress"] for r in result["records"] if r["type"] == "A"}
        self.assertEqual(addresses, {
            f"ns.{ZONE}": "192.0.2.53", f"api.{ZONE}": "192.0.2.10", f"*.apps.{ZONE}": "192.0.2.11",
        })
        self.assertEqual(result["records"][0]["rData"]["serial"], 42)

    def test_rejects_unloaded_or_incomplete_transfer(self):
        for text in ("; Transfer failed.", TRANSFER.rsplit("\n", 1)[0]):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_raises_legacy_expiry_without_changing_ttls_or_original_export(self):
        legacy = TRANSFER.replace(" 300 IN ", " 604800 IN ").replace("42 3600 600 604800 300", "42 604800 86400 3600 300")
        result = self.parse(legacy)
        self.assertEqual(result["source_zone_file"], legacy)
        self.assertEqual(result["records"][0]["rData"]["expire"], 691200)
        self.assertEqual([r["ttl"] for r in result["records"]], [604800, 604800, 604800, 600, 600])

    def test_preserves_sufficient_expiry_and_covers_largest_record_ttl(self):
        self.assertEqual(self.parse()["records"][0]["rData"]["expire"], 604800)
        result = self.parse(TRANSFER.replace(" 600 IN ", " 1209600 IN "))
        self.assertEqual(result["records"][0]["rData"]["expire"], 1209600)

    def test_rejects_retry_longer_than_refresh(self):
        with self.assertRaisesRegex(ValueError, "retry exceeds refresh"):
            self.parse(TRANSFER.replace("42 3600 600", "42 600 3600"))

    def test_rejects_unhandled_record_types(self):
        with self.assertRaises(ValueError):
            self.parse(TRANSFER + f"\nalias.{ZONE}. 300 IN CNAME api.{ZONE}.")

    def test_rejects_out_of_zone_records(self):
        with self.assertRaises(ValueError):
            self.parse(TRANSFER + "\nother.example.org. 300 IN A 192.0.2.5")

    def test_rejects_unexpected_nameserver_address(self):
        with self.assertRaises(ValueError):
            self.parse(TRANSFER.replace("192.0.2.100", "192.0.2.99"))

    def test_comparison_ignores_soa_serial_but_detects_address_drift(self):
        template = Environment().from_string((ROOT / "roles/technitium_zone/templates/records.j2").read_text())
        records = self.parse()["records"]
        def render(value):
            return template.render(technitium_zone_render_records=value, technitium_zone_compare_serial=True)
        original = render(records)
        updated = copy.deepcopy(records)
        updated[0]["rData"]["serial"] += 100
        self.assertEqual(render(updated), original)
        updated[-1]["rData"]["ipAddress"] = "192.0.2.99"
        self.assertNotEqual(render(updated), original)
        self.assertFalse(render([]).strip())


if __name__ == "__main__":
    unittest.main()
