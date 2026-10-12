import hashlib
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from infra.terraform.host.console_contract import parse_installation
from infra.terraform.host.console_sources import ConsoleDownload, MetadataSource
from infra.terraform.host.contracts import HostError, parse_manifest
from tests.fixtures.host_release import HOST_DIGEST, PUBLIC_BASE, VNIC_CONTENT, installation


class ConsoleInputTests(unittest.TestCase):
    def test_resolves_backend_only_from_exact_private_vnic_and_preserves_manifest_checks(self):
        content, _ = installation()
        desired = parse_installation(content, VNIC_CONTENT, HOST_DIGEST, "us-ashburn-1")
        manifest = parse_manifest(desired.manifest, desired.digest, HOST_DIGEST)
        self.assertEqual(manifest["runtime"]["backend_host"], "10.40.1.10:8080")
        self.assertEqual(manifest["runtime"]["version"], 2)
        self.assertEqual(desired.generation, 0)
        self.assertEqual(desired.artifact_base, PUBLIC_BASE)

    def test_untrusted_shape_url_or_runtime_fails_without_echoing_data(self):
        content, _ = installation()
        original = json.loads(content)
        cases = [dict(original, generation=True), dict(original, generation=-1),
                 dict(original, generation=1000001), dict(original, password="private-marker")]
        for url in (PUBLIC_BASE + "?private-marker", PUBLIC_BASE.replace("https:", "http:"),
                    PUBLIC_BASE.replace("objectstorage.", "private-marker@objectstorage."),
                    PUBLIC_BASE.replace("oraclecloud.com", "oraclecloud.com.evil.example"),
                    PUBLIC_BASE + "../", PUBLIC_BASE + "#private-marker"):
            cases.append(dict(original, artifact_base=url))
        for runtime_change in ({"backend_host": "10.40.1.20:8080"}, {"version": 1},
                               {"region": "us-phoenix-1"}, {"password": "private-marker"}):
            cases.append(dict(original, manifest=dict(original["manifest"],
                runtime=dict(original["manifest"]["runtime"], **runtime_change))))
        for value in cases:
            with self.subTest(value=list(value)), self.assertRaises(HostError) as raised:
                parse_installation(json.dumps(value).encode(), VNIC_CONTENT, HOST_DIGEST, "us-ashburn-1")
            self.assertNotIn("private-marker", str(raised.exception))
        for raw in (b"x" * 16385, b'{}', content[:-1] + b',"version":1}'):
            with self.subTest(raw=raw[:10]), self.assertRaises(HostError):
                parse_installation(raw, VNIC_CONTENT, HOST_DIGEST, "us-ashburn-1")

    def test_ambiguous_or_outside_vnic_and_incompatible_helper_are_rejected(self):
        content, _ = installation()
        for vnics in ([], [{"privateIp": "127.0.0.1"}], [{"privateIp": "10.40.2.10"}],
                      [{"privateIp": "10.40.1.0"}], [{"privateIp": "10.40.1.255"}],
                      [{"privateIp": "10.40.1.10"}] * 2):
            with self.subTest(vnics=vnics), self.assertRaises(HostError):
                parse_installation(content, json.dumps(vnics).encode(), HOST_DIGEST, "us-ashburn-1")
        with self.assertRaises(HostError):
            parse_installation(content, VNIC_CONTENT, "b" * 64, "us-ashburn-1")


def response(content, status=200, **headers):
    result = Mock(status=status)
    body = BytesIO(content)
    fields = {"Content-Length": str(len(content)), **headers}
    result.getheader.side_effect = lambda key, default=None: fields.get(key, default)
    result.read1.side_effect = body.read
    return result


class ConsoleTransportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.target = Path(temporary.name) / "image.tar"
        self.raw, self.archive = installation()
        self.desired = parse_installation(self.raw, VNIC_CONTENT, HOST_DIGEST, "us-ashburn-1")
        self.connection = Mock()
        self.connection.getresponse.return_value = response(self.archive)
        self.connect = Mock(return_value=self.connection)
        self.download = ConsoleDownload(self.desired, connect=self.connect)
        self.image_digest = hashlib.sha256(self.archive).hexdigest()
        self.image_name = "images/" + self.image_digest + ".tar"

    def fetch(self):
        self.download.fetch(self.image_name, self.target, self.image_digest,
                            max_bytes=len(self.archive), expected_size=len(self.archive))

    def test_public_image_is_pinned_and_has_no_authorization_or_redirects(self):
        self.fetch()
        self.assertEqual(self.target.read_bytes(), self.archive)
        self.connect.assert_called_once_with("objectstorage.us-ashburn-1.oraclecloud.com", timeout=30)
        args, options = self.connection.request.call_args
        self.assertEqual(args[:2], ("GET", "/n/example/b/public-demo/o/images%2F" + self.image_digest + ".tar"))
        self.assertNotIn("Authorization", options.get("headers", {}))
        self.connection.close.assert_called_once()

    def test_local_manifest_never_downloads_installation_details(self):
        self.download.fetch("releases/" + self.desired.digest + ".json", self.target,
                            self.desired.digest, max_bytes=65536)
        self.assertEqual(self.target.read_bytes(), self.desired.manifest)
        self.connect.assert_not_called()

    def test_redirect_truncation_encoding_size_hash_and_transport_errors_fail_privately(self):
        bad = [response(self.archive, status=302), response(self.archive[:-1]),
               response(self.archive + b"x"), response(b"X" * len(self.archive)),
               response(self.archive[:-1], **{"Content-Length": str(len(self.archive))}),
               response(self.archive + b"x", **{"Content-Length": str(len(self.archive))}),
               response(self.archive, **{"Content-Encoding": "gzip"}),
               response(self.archive, **{"Content-Length": "private-marker"}),
               TimeoutError("private-marker")]
        for reply in bad:
            with self.subTest(reply=type(reply).__name__):
                self.target.unlink(missing_ok=True)
                self.connection.reset_mock()
                self.connection.getresponse.side_effect = reply if isinstance(reply, Exception) else None
                self.connection.getresponse.return_value = reply
                with self.assertRaises(HostError) as raised:
                    self.fetch()
                self.assertNotIn("private-marker", str(raised.exception))
                self.connection.request.assert_called_once()
                self.connection.close.assert_called_once()
                if not isinstance(reply, Exception):
                    reply.close.assert_called_once()

    def test_window_exhaustion_stops_before_another_body_read(self):
        reply = response(self.archive)
        self.connection.getresponse.return_value = reply
        self.download.monotonic = Mock(side_effect=[0, 601])
        with self.assertRaises(HostError):
            self.fetch()
        reply.read1.assert_not_called()

    def test_window_exhaustion_after_first_chunk_preserves_read_bound(self):
        reply = response(self.archive)
        self.connection.getresponse.return_value = reply
        self.download.monotonic = Mock(side_effect=[0, 0, 601])
        with self.assertRaises(HostError):
            self.fetch()
        reply.read1.assert_called_once()

    def test_wrong_object_request_or_existing_file_is_preserved(self):
        self.target.write_bytes(b"preserve")
        with self.assertRaises(HostError):
            self.fetch()
        self.assertEqual(self.target.read_bytes(), b"preserve")
        self.connect.assert_not_called()
        self.target.unlink()
        with self.assertRaises(HostError):
            self.download.fetch("images/" + "a" * 64 + ".tar", self.target,
                                "a" * 64, max_bytes=len(self.archive))
        self.connect.assert_not_called()

    def test_metadata_uses_only_fixed_v2_paths_and_header_and_keeps_other_data_private(self):
        metadata = json.dumps({"energy_ai_install": self.raw.decode(), "unrelated": "private-marker"}).encode()
        first, second = Mock(), Mock()
        first.getresponse.return_value = response(metadata)
        second.getresponse.return_value = response(VNIC_CONTENT)
        connect = Mock(side_effect=[first, second])
        result = MetadataSource(connect=connect).read()
        self.assertEqual(result, (self.raw, VNIC_CONTENT))
        for connection, path in ((first, "/opc/v2/instance/metadata/"), (second, "/opc/v2/vnics/")):
            connection.request.assert_called_once_with("GET", path, headers={"Authorization": "Bearer Oracle"})
            connection.close.assert_called_once()
        self.assertTrue(all(call.args == ("169.254.169.254",) and call.kwargs == {"timeout": 10}
                            for call in connect.call_args_list))

    def test_metadata_failure_or_oversize_does_not_request_another_source(self):
        for reply in (response(b"{}", status=302), response(b"x" * 65537),
                      response(b'{"energy_ai_install": {}}'), response(b'{}')):
            with self.subTest(reply=reply.status):
                self.connect.reset_mock()
                self.connection.getresponse.return_value = reply
                with self.assertRaises(HostError):
                    MetadataSource(connect=self.connect).read()
                self.connect.assert_called_once()
