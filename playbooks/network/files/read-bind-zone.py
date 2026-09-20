"""Read and validate a live BIND OCP zone; emit JSON only, never modify BIND."""
import ipaddress
import json
import re
import subprocess
import sys


def parse_zone(text, zone, source_ip, target_ip):
    """Translate the observed A/NS/SOA schema, failing on any unhandled type."""
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", zone):
        raise ValueError("Invalid zone name")
    ipaddress.IPv4Address(source_ip)
    ipaddress.IPv4Address(target_ip)
    records = []
    soa_records = []
    for line in text.splitlines():
        if not line.strip() or line.startswith(";"):
            continue
        parts = line.split()
        if len(parts) < 5 or parts[2] != "IN":
            raise ValueError("Unexpected AXFR record format")
        name, ttl, _, kind, *data = parts
        name = name.rstrip(".").lower()
        if name != zone and not name.endswith("." + zone):
            raise ValueError("Out-of-zone record")
        record = {"name": name, "ttl": int(ttl), "type": kind}
        if kind == "A" and len(data) == 1:
            record["rData"] = {"ipAddress": str(ipaddress.IPv4Address(data[0]))}
        elif kind == "NS" and len(data) == 1 and name == zone:
            record["rData"] = {"nameServer": data[0].rstrip(".").lower()}
        elif kind == "SOA" and len(data) == 7 and name == zone:
            record["rData"] = dict(zip(
                ["primaryNameServer", "responsiblePerson", "serial", "refresh", "retry", "expire", "minimum"],
                [data[0].rstrip(".").lower(), data[1].rstrip(".").lower(), *map(int, data[2:])],
            ))
            soa_records.append(record)
        else:
            raise ValueError("Unhandled record type or layout; review before migration")
        if record not in records:
            records.append(record)
    if len(soa_records) != 2 or soa_records[0] != soa_records[1]:
        raise ValueError("Incomplete or inconsistent AXFR; zone may not be loaded")
    nameservers = {r["rData"]["nameServer"] for r in records if r["type"] == "NS"}
    if not nameservers or soa_records[0]["rData"]["primaryNameServer"] not in nameservers:
        raise ValueError("Unexpected zone authority layout")
    for nameserver in nameservers:
        addresses = [r for r in records if r["type"] == "A" and r["name"] == nameserver]
        if len(addresses) != 1 or addresses[0]["rData"]["ipAddress"] != source_ip:
            raise ValueError("Nameserver address does not match the migration source")
        addresses[0]["rData"]["ipAddress"] = target_ip
    soa = soa_records[0]["rData"]
    if soa["retry"] > soa["refresh"]:
        raise ValueError("SOA retry exceeds refresh; review before migration")
    # Technitium requires TTL <= EXPIRE and REFRESH <= EXPIRE. Keep TTLs
    # intact and allow at least one refresh/retry interval before expiry.
    soa["expire"] = max(soa["expire"], max(r["ttl"] for r in records), soa["refresh"] + soa["retry"])
    return {"zone": zone, "records": records, "source_zone_file": text}


if __name__ == "__main__":
    zone, source_ip, target_ip = sys.argv[1:]
    result = subprocess.run(
        ["dig", "@127.0.0.1", zone, "AXFR", "+noall", "+answer", "+time=5", "+tries=1"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    print(json.dumps(parse_zone(result.stdout, zone, source_ip, target_ip)))
