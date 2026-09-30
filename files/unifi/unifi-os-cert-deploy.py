#!/usr/bin/python3
"""Deploy Certbot certificates through UniFi OS Server's local certificate API.

Verified against the installed 5.1.42 implementation. This is an internal API,
not a stable public contract. Never replace UniFi's internal identity certs.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import time
from uuid import UUID


def run(argv, data=None):
    result = subprocess.run(argv, input=data, capture_output=True, cwd="/", timeout=45)
    if result.returncode:
        # Child output and API bodies can contain private certificate material.
        raise RuntimeError(f"{Path(argv[0]).name} failed (exit {result.returncode}); output suppressed")
    return result.stdout


class CertificateAPI:
    def __init__(self, config):
        self.config = config

    def __call__(self, method, path="", body=None):
        argv = [
            "/usr/sbin/runuser", "-u", self.config["user"], "--",
            "/usr/bin/podman", "exec", "-i", self.config["container"],
            "curl", "--noproxy", "*", "--silent", "--show-error", "--fail",
            "--max-time", "30", "--request", method,
            "--header", "Content-Type: application/json",
        ]
        data = None
        if body is not None:
            argv += ["--data-binary", "@-"]
            data = json.dumps(body).encode()
        # IPC is reachable only inside the vendor container; no web login needed.
        argv += ["http://127.0.0.1:11081/api/userCertificates" + path]
        result = run(argv, data)
        return json.loads(result) if result else None


def certificate_list(api):
    records = api("GET")
    if not isinstance(records, list):
        raise RuntimeError("Unexpected certificate API response; check UniFi OS compatibility")
    for record in records:
        UUID(record["id"])
        if not isinstance(record.get("active"), bool) or not isinstance(record.get("fingerprint"), str):
            raise RuntimeError("Unexpected certificate metadata")
    if sum(record["active"] for record in records) > 1:
        raise RuntimeError("Multiple active console certificates")
    return records


def fingerprint(value):
    return value.replace(":", "").lower()


def load_certificate(lineage, domain):
    cert = (lineage / "cert.pem").read_bytes()
    chain = (lineage / "fullchain.pem").read_bytes()
    key = (lineage / "privkey.pem").read_bytes()
    run(["openssl", "x509", "-noout", "-checkend", "0", "-checkhost", domain], cert)
    run(["openssl", "verify", "-purpose", "sslserver", "-verify_hostname", domain,
         "-untrusted", str(lineage / "chain.pem"), str(lineage / "cert.pem")])
    public_cert = run(["openssl", "x509", "-pubkey", "-noout"], cert)
    public_key = run(["openssl", "pkey", "-pubout"], key)
    if public_cert != public_key:
        raise RuntimeError("Certificate and private key do not match")
    der = ssl.PEM_cert_to_DER_cert(cert.decode())
    first_certificate = chain.decode().split("-----END CERTIFICATE-----", 1)[0] + "-----END CERTIFICATE-----\n"
    if ssl.PEM_cert_to_DER_cert(first_certificate) != der:
        raise RuntimeError("Full chain does not start with the issued certificate")
    # UniFi's X509Certificate.fingerprint field uses SHA-1 as an identifier only.
    return chain.decode(), key.decode(), hashlib.sha1(der).hexdigest(), hashlib.sha256(der).hexdigest()


def verify_served(config, expected):
    context = ssl.create_default_context()
    for attempt in range(12):
        try:
            with socket.create_connection(("127.0.0.1", config["port"]), timeout=5) as connection:
                with context.wrap_socket(connection, server_hostname=config["domain"]) as tls:
                    if hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest() == expected:
                        return
        except (OSError, ssl.SSLError):
            pass
        if attempt < 11:
            time.sleep(5)
    raise RuntimeError("Console did not serve the expected trusted certificate")


def deploy(api, records, domain, chain, key, sha1, sha256, verify):
    previous = next((item for item in records if item["active"]), None)
    target = next((item for item in records if fingerprint(item["fingerprint"]) == sha1), None)
    changed = False
    if target is None:
        target = api("POST", body={"name": f"certbot:{domain}:{sha256[:16]}", "cert": chain, "key": key})
        UUID(target["id"])
        if fingerprint(target["fingerprint"]) != sha1:
            raise RuntimeError("Imported certificate fingerprint mismatch")
        changed = True
    path = f'/{target["id"]}/status'
    if target.get("active"):
        verify()
        return changed
    try:
        api("PUT", path, {"active": True})
        verify()
    except Exception as error:
        try:
            # Restore the previous selection, or the vendor default if none existed.
            if previous:
                api("PUT", f'/{previous["id"]}/status', {"active": True})
            else:
                api("PUT", path, {"active": False})
        except Exception:
            raise RuntimeError("Certificate activation failed; rollback also failed. Inspect the console.") from error
        raise RuntimeError("Certificate activation failed; previous certificate selection restored") from error
    # Preserve existing certificates, including the previous one, for rollback.
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-api", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    config = json.loads(Path("/etc/letsencrypt/unifi-os.json").read_text())
    lineage = Path("/etc/letsencrypt/live") / config["domain"]
    renewed = os.environ.get("RENEWED_LINEAGE")
    if renewed and Path(renewed).resolve() != lineage.resolve():
        return  # The deploy directory runs for every certificate on the host.
    with open("/run/lock/unifi-os-cert-deploy.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        api = CertificateAPI(config)
        records = certificate_list(api)
        if args.check_api:
            print("UniFi OS local certificate API available")
            return
        chain, key, sha1, sha256 = load_certificate(lineage, config["domain"])
        changed = deploy(api, records, config["domain"], chain, key, sha1, sha256,
                         lambda: verify_served(config, sha256))
        print("Certificate deployed" if changed else "Certificate already active and verified")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Never print exception payloads/tracebacks: API responses may include keys.
        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print(f"UniFi certificate deployment failed: {message}", file=sys.stderr)
        sys.exit(1)
