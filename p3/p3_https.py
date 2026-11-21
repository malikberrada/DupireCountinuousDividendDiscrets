"""Verified HTTPS for market sources and the short-lived Deutsche Börse redirects."""

import http.client
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

WINDOWS = sys.platform == "win32"
STORAGE = "https://storage.googleapis.com/"


class CertificateTrustError(RuntimeError):
    """A certificate failure is terminal for this acquisition, even with a bundled snapshot."""


def public_url(url):
    # Redirect targets can carry a signed query. The host and path identify the source.
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc.rsplit("@", 1)[-1], p.path, "", ""))


def ca_bundle():
    value = os.environ.get("P3_CA_BUNDLE")
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_file():
        raise ValueError("Fichier PEM de confiance introuvable : " + str(path))
    return str(path.resolve())


def client_context():
    if WINDOWS:
        from p3_vendor import truststore

        # CryptoAPI builds the certificate chain on this machine, including intermediates.
        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        if os.environ.get("SSL_CERT_FILE"):
            # Preserve an existing Python trust setting without overriding Schannel in curl.
            ctx.set_default_verify_paths()
    else:
        ctx = ssl.create_default_context()
    cafile = ca_bundle()
    if cafile:
        try:
            ctx.load_verify_locations(cafile=cafile)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Chargement du fichier PEM impossible ({cafile}) : {exc}") from exc
    ctx.set_alpn_protocols(["http/1.1"])
    return ctx


def certificate_error(url, backend, cause):
    return CertificateTrustError(
        f"Échec de vérification du certificat TLS pour {public_url(url)} ({backend}). "
        f"{cause}. Si votre réseau utilise une autorité privée, P3_CA_BUNDLE accepte "
        "un fichier PEM d'autorités de confiance fourni par votre administrateur."
    )


class SourceHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        try:
            return super().https_open(req)
        except (ssl.SSLError, urllib.error.URLError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(reason, ssl.SSLCertVerificationError) or (
                isinstance(reason, ssl.SSLError) and getattr(reason, "reason", None) == "CERTIFICATE_VERIFY_FAILED"
            ):
                backend = "Windows CryptoAPI" if WINDOWS else "Python/OpenSSL"
                raise certificate_error(req.full_url, backend, reason) from exc
            raise urllib.error.URLError(f"{public_url(req.full_url)} — {reason}") from exc


class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != "https":
            raise ValueError("Redirection vers une URL hors HTTPS depuis " + public_url(req.full_url))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url_or_request, *, timeout):
    url = url_or_request.full_url if isinstance(url_or_request, urllib.request.Request) else url_or_request
    if urlsplit(url).scheme.lower() != "https":
        raise ValueError("La source doit utiliser HTTPS.")
    opener = urllib.request.build_opener(
        HTTPSRedirectHandler(), SourceHTTPSHandler(context=client_context())
    )
    return opener.open(url_or_request, timeout=timeout)


def download(url_or_request, dest, *, timeout):
    with open_url(url_or_request, timeout=timeout) as response, dest.open("wb") as output:
        shutil.copyfileobj(response, output, 1 << 20)
        length = response.headers.get("Content-Length")
        if length is not None and output.tell() != int(length):
            raise http.client.IncompleteRead(b"")


def curl_executable():
    if not WINDOWS:
        return shutil.which("curl")
    root = os.environ.get("SystemRoot")
    if root:
        # Sysnative reaches the native binary from 32-bit Python on 64-bit Windows.
        for folder in ("Sysnative", "System32"):
            exe = Path(root) / folder / "curl.exe"
            if exe.is_file():
                return str(exe)
    return None


def download_db(url, dest):
    # Keep the storage connection alive through the provider's short-lived signed redirect.
    url += "?t=" + str(time.time_ns())
    exe = curl_executable()
    if not exe:
        return download(url, dest, timeout=180)
    flags = ["--silent", "--show-error", "--proto", "=https", "--proto-redir", "=https"]
    cafile = ca_bundle()
    if cafile:
        flags.extend(["--cacert", cafile])
    command = [
        exe, "--disable", *flags, "--max-time", "20", "--output", os.devnull, STORAGE,
        "--next", *flags, "--fail", "--location", "--max-time", "180", "--output", str(dest),
        "--write-out", "%{url_effective}", url,
    ]
    result = subprocess.run(command, capture_output=True)
    if result.returncode == 0:
        return
    effective = result.stdout.decode("utf-8", "replace").strip() or url
    errors = result.stderr.decode("utf-8", "replace").splitlines()
    prefix = f"curl: ({result.returncode})"
    detail = next((line for line in reversed(errors) if line.startswith(prefix)), prefix)
    detail = re.sub(r"https?://[^\s]+", lambda m: public_url(m.group()), detail)
    if result.returncode in (51, 60, 77, 83, 91):
        backend = "curl système/Schannel" if WINDOWS else "curl"
        raise certificate_error(effective, backend, detail)
    raise OSError(f"Échec du téléchargement {public_url(effective)}. {detail}")
