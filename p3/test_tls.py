import http.server
import os
import shutil
import ssl
import subprocess
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import capture
import euronext
import p3_https


class TransportTests(unittest.TestCase):
    def test_windows_native_context_is_local_to_the_client(self):
        from p3_vendor import truststore

        original = ssl.SSLContext
        with patch.object(p3_https, "WINDOWS", True), patch.dict(os.environ, {"SSL_CERT_FILE": "", "P3_CA_BUNDLE": ""}):
            ctx = p3_https.client_context()
        self.assertIsInstance(ctx, truststore.SSLContext)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertIs(ssl.SSLContext, original)

    def test_windows_curl_is_the_system_executable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "System32" / "curl.exe"
            exe.parent.mkdir()
            exe.touch()
            with patch.dict(os.environ, {"SystemRoot": str(root)}), patch.object(p3_https, "WINDOWS", True):
                self.assertEqual(Path(p3_https.curl_executable()), exe)
                exe.unlink()
                self.assertIsNone(p3_https.curl_executable())

    def test_curl_certificate_failure_reports_redirect_and_does_not_publish(self):
        result = subprocess.CompletedProcess(
            [], 60, stdout=b"https://storage.googleapis.com/example/file?signature=private",
            stderr=b"curl: (60) SSL certificate problem: unable to get local issuer certificate",
        )
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ca = root / "private CA bundle.pem"
            ca.touch()
            target = root / "data.gz"
            work = root / "data.part"
            item = {"service": "Deutsche Boerse", "url": "https://mfs.deutsche-boerse.com/api/download/example"}
            with (
                patch.dict(os.environ, {"P3_CA_BUNDLE": str(ca)}),
                patch.object(p3_https, "curl_executable", return_value="system-curl"),
                patch.object(p3_https.subprocess, "run", return_value=result) as run,
                self.assertRaises(p3_https.CertificateTrustError) as error,
            ):
                capture.fetch_checked(item, work, target)
            run.assert_called_once()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:2], ["system-curl", "--disable"])
            ca_arguments = [argv[i + 1] for i, value in enumerate(argv) if value == "--cacert"]
            self.assertEqual(ca_arguments, [str(ca.resolve())] * 2)
            self.assertIn("https://storage.googleapis.com/example/file", str(error.exception))
            self.assertNotIn("signature", str(error.exception))
            self.assertFalse(target.exists())

    def test_trust_failure_is_distinct_from_rolling_data(self):
        with TemporaryDirectory() as directory:
            cache = Path(directory)
            with (
                patch.object(p3_https, "download", side_effect=p3_https.CertificateTrustError("issuer")) as get,
                self.assertRaises(p3_https.CertificateTrustError),
            ):
                euronext.acquire(cache)
            get.assert_called_once()
            self.assertFalse(list(cache.iterdir()))


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL command required to create temporary test certificates")
class LocalChainTests(unittest.TestCase):
    @classmethod
    def start_server(cls, handler, context=None):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.addClassCleanup(server.server_close)
        if context is not None:
            server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        cls.addClassCleanup(thread.join)
        cls.addClassCleanup(server.shutdown)
        return server.server_port

    @classmethod
    def setUpClass(cls):
        tmp = TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.root = Path(tmp.name)
        cls.ca = cls.root / "ca.pem"

        def openssl(*args):
            subprocess.run([shutil.which("openssl"), *args], cwd=cls.root, check=True, capture_output=True)

        openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj",
                "/CN=P3 local test CA", "-addext", "basicConstraints=critical,CA:TRUE",
                "-addext", "subjectKeyIdentifier=hash",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign", "-keyout", "ca.key", "-out", "ca.pem")
        # Schannel checks the issuing CA's revocation list when curl uses a custom CA.
        (cls.root / "index.txt").touch()
        (cls.root / "crlnumber").write_text("01\n", encoding="ascii")
        (cls.root / "crl.cnf").write_text(
            "[ca]\ndefault_ca=authority\n[authority]\ndatabase=index.txt\n"
            "certificate=ca.pem\nprivate_key=ca.key\ndefault_md=sha256\ndefault_crl_days=2\n"
            "crlnumber=crlnumber\ncrl_extensions=crl_ext\n[crl_ext]\nauthorityKeyIdentifier=keyid:always\n",
            encoding="ascii",
        )
        openssl("ca", "-batch", "-gencrl", "-config", "crl.cnf", "-out", "ca-crl.pem")
        openssl("crl", "-in", "ca-crl.pem", "-outform", "DER", "-out", "ca.crl")
        crl = (cls.root / "ca.crl").read_bytes()

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", f"https://127.0.0.1:{self.server.server_port}/final?signature=private")
                    self.end_headers()
                    return
                is_crl = self.path == "/ca.crl"
                body = crl if is_crl else b"OK"
                self.send_response(200)
                self.send_header("Content-Type", "application/pkix-crl" if is_crl else "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        crl_port = cls.start_server(Handler)
        openssl("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=localhost",
                "-keyout", "server.key", "-out", "server.csr")
        (cls.root / "server.ext").write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n"
            "authorityKeyIdentifier=keyid,issuer\nsubjectKeyIdentifier=hash\n"
            f"crlDistributionPoints=URI:http://127.0.0.1:{crl_port}/ca.crl\n", encoding="ascii"
        )
        openssl("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                "-CAcreateserial", "-days", "2", "-extfile", "server.ext", "-out", "server.pem")
        openssl("verify", "-CAfile", "ca.pem", "-crl_check", "-CRLfile", "ca-crl.pem", "server.pem")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cls.root / "server.pem", cls.root / "server.key")
        tls_port = cls.start_server(Handler, ctx)
        cls.base = f"https://localhost:{tls_port}"
        cls.redirect_target = f"https://127.0.0.1:{tls_port}/final"

    def test_unknown_issuer_custom_ca_and_redirect_hostname(self):
        local = {"no_proxy": "localhost,127.0.0.1", "NO_PROXY": "localhost,127.0.0.1"}
        for native_context in (False, True):
            with self.subTest(native=native_context), patch.object(p3_https, "WINDOWS", native_context):
                with patch.dict(os.environ, dict(local, P3_CA_BUNDLE="")):
                    with self.assertRaises(p3_https.CertificateTrustError) as error:
                        p3_https.open_url(self.base + "/source", timeout=5)
                    self.assertIn(self.base + "/source", str(error.exception))
                with patch.dict(os.environ, dict(local, P3_CA_BUNDLE=str(self.ca))):
                    with p3_https.open_url(self.base + "/source", timeout=5) as response:
                        self.assertEqual(response.read(), b"OK")
                    with self.assertRaises(p3_https.CertificateTrustError) as error:
                        p3_https.open_url(self.base + "/redirect", timeout=5)
                    self.assertIn(self.redirect_target, str(error.exception))
                    self.assertNotIn("signature", str(error.exception))

    @unittest.skipUnless(p3_https.curl_executable(), "curl required for storage redirect test")
    def test_storage_transfer_honors_ca_and_checks_redirect(self):
        env = {"P3_CA_BUNDLE": str(self.ca), "NO_PROXY": "localhost,127.0.0.1",
               "no_proxy": "localhost,127.0.0.1"}
        with patch.dict(os.environ, env), patch.object(p3_https, "STORAGE", self.base + "/warm"):
            dest = self.root / "download.part"
            p3_https.download_db(self.base + "/source", dest)
            self.assertEqual(dest.read_bytes(), b"OK")
            with self.assertRaises(p3_https.CertificateTrustError) as error:
                p3_https.download_db(self.base + "/redirect", dest)
            self.assertIn(self.redirect_target, str(error.exception))
            self.assertNotIn("signature", str(error.exception))


if __name__ == "__main__":
    unittest.main()
