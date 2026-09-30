"""Exercise certificate activation and rollback without changing a real console."""
import importlib.util
import hashlib
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import Mock

SCRIPT = Path(__file__).parents[1] / "files/unifi/unifi-os-cert-deploy.py"
SPEC = importlib.util.spec_from_file_location("unifi_certificate", SCRIPT)
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)

OLD = "11111111-1111-4111-8111-111111111111"
NEW = "22222222-2222-4222-8222-222222222222"


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.previous = {"id": OLD, "fingerprint": "00:11", "active": True}
        self.target = {"id": NEW, "fingerprint": "AA:BB", "active": False}
        self.verify = Mock()
        self.calls = []

        def api(method, path="", body=None):
            self.calls.append((method, path, body))
            return self.target.copy() if method == "POST" else None

        self.api = api

    def deploy(self, records):
        return hook.deploy(self.api, records, "unifi.example.com", "chain", "key",
                           "aabb", "c" * 64, self.verify)

    def test_import_activate_then_verify_without_deleting_previous(self):
        self.assertTrue(self.deploy([self.previous]))
        self.assertEqual([call[0] for call in self.calls], ["POST", "PUT"])
        self.assertEqual(self.calls[1], ("PUT", f"/{NEW}/status", {"active": True}))
        self.verify.assert_called_once()

    def test_unchanged_certificate_performs_no_writes(self):
        self.target["active"] = True
        self.assertFalse(self.deploy([self.target]))
        self.assertEqual(self.calls, [])
        self.verify.assert_called_once()

    def test_retry_reuses_imported_certificate(self):
        self.assertTrue(self.deploy([self.previous, self.target]))
        self.assertEqual([call[0] for call in self.calls], ["PUT"])

    def test_failed_verification_restores_previous_selection(self):
        self.verify.side_effect = RuntimeError("verification failed")
        with self.assertRaisesRegex(RuntimeError, "previous certificate selection restored"):
            self.deploy([self.previous])
        self.assertEqual(self.calls[-1], ("PUT", f"/{OLD}/status", {"active": True}))

    def test_first_install_failure_restores_vendor_default(self):
        self.verify.side_effect = RuntimeError("verification failed")
        with self.assertRaisesRegex(RuntimeError, "previous certificate selection restored"):
            self.deploy([])
        self.assertEqual(self.calls[-1], ("PUT", f"/{NEW}/status", {"active": False}))

    def test_activation_failure_after_server_write_also_rolls_back(self):
        original = self.api

        def api(method, path="", body=None):
            result = original(method, path, body)
            if method == "PUT" and path == f"/{NEW}/status":
                raise RuntimeError("connection lost")
            return result

        self.api = api
        with self.assertRaisesRegex(RuntimeError, "previous certificate selection restored"):
            self.deploy([self.previous])
        self.assertEqual(self.calls[-1][1], f"/{OLD}/status")

    def test_unexpected_api_schema_fails_closed(self):
        for response in ({"error": "unauthorized"}, [{"id": NEW, "active": False}]):
            with self.assertRaises(RuntimeError):
                hook.certificate_list(lambda *args: response)

    def test_private_material_uses_stdin_not_command_arguments(self):
        with unittest.mock.patch.object(hook, "run", return_value=b'{}') as command:
            hook.CertificateAPI({"user": "uosserver", "container": "uosserver"})(
                "POST", body={"key": "private-material"})
        argv, body = command.call_args.args
        self.assertNotIn("private-material", " ".join(argv))
        self.assertIn(b"private-material", body)

    def test_full_chain_comparison_uses_only_leaf_certificate(self):
        # OpenSSL validation is separate; exercise the PEM-chain parsing here.
        leaf = ssl.DER_cert_to_PEM_cert(b"leaf-certificate")
        intermediate = ssl.DER_cert_to_PEM_cert(b"intermediate-certificate")
        with tempfile.TemporaryDirectory() as directory:
            lineage = Path(directory)
            (lineage / "cert.pem").write_text(leaf)
            (lineage / "fullchain.pem").write_text(leaf + intermediate)
            (lineage / "privkey.pem").write_text("private-key")
            with unittest.mock.patch.object(hook, "run", return_value=b"same-public-key"):
                chain, key, sha1, sha256 = hook.load_certificate(lineage, "unifi.example.com")
                self.assertEqual(chain, leaf + intermediate)
                self.assertEqual(sha256, hashlib.sha256(b"leaf-certificate").hexdigest())
                (lineage / "fullchain.pem").write_text(intermediate + leaf)
                with self.assertRaisesRegex(RuntimeError, "Full chain"):
                    hook.load_certificate(lineage, "unifi.example.com")

    def test_mismatched_key_is_rejected_before_import(self):
        with tempfile.TemporaryDirectory() as directory:
            lineage = Path(directory)
            for name in ["cert.pem", "fullchain.pem", "privkey.pem"]:
                (lineage / name).write_text("test input")
            with unittest.mock.patch.object(hook, "run", side_effect=[b"", b"", b"public-a", b"public-b"]):
                with self.assertRaisesRegex(RuntimeError, "private key do not match"):
                    hook.load_certificate(lineage, "unifi.example.com")


if __name__ == "__main__":
    unittest.main()
