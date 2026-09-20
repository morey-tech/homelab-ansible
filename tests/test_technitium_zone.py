"""Offline regression check for Technitium managed-record comparison."""
import copy
from pathlib import Path
import unittest

from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]


class ZoneComparisonTest(unittest.TestCase):
    def test_comparison_ignores_soa_serial_but_detects_address_drift(self):
        template = Environment().from_string((ROOT / "roles/technitium_zone/templates/records.j2").read_text())
        records = [
            {"name": "cluster.example.org", "ttl": 300, "type": "SOA", "rData": {
                "primaryNameServer": "ns.cluster.example.org", "responsiblePerson": "admin.cluster.example.org",
                "serial": 42, "refresh": 3600, "retry": 600, "expire": 604800, "minimum": 300,
            }},
            {"name": "api.cluster.example.org", "ttl": 300, "type": "A", "rData": {"ipAddress": "192.0.2.10"}},
        ]

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
