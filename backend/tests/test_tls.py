"""AIA chain repair — `app/scrapers/utils/tls.py`.

No test here opens a socket. Certificates are minted in-process so the AIA
extension is genuinely parsed and the recovered intermediate is genuinely
loaded into an `SSLContext`; only the two I/O seams — reading the leaf and
downloading the intermediate — are stubbed.
"""

from __future__ import annotations

import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID, NameOID

from app.scrapers.utils import tls
from app.scrapers.utils.tls import TLSChainError, ssl_context_for

ISSUER_URL = "http://secure.example-ca.test/cacert/intermediate.crt"
ROOT_URL = "http://secure.example-ca.test/cacert/root.crt"


def _key():
    # 1024 bits is nowhere near safe for real use; these certificates never
    # leave the test process and larger keys make the suite crawl.
    return rsa.generate_private_key(public_exponent=65537, key_size=1024)


def _certificate(
    common_name: str,
    *,
    issuer_name: str | None = None,
    ca_issuer_url: str | None = None,
    is_ca: bool = False,
) -> x509.Certificate:
    """A throwaway self-signed certificate, optionally carrying an AIA URI."""
    key = _key()
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, issuer_name or common_name)]
    )
    now = datetime.now(timezone.utc)

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    if ca_issuer_url:
        builder = builder.add_extension(
            x509.AuthorityInformationAccess([
                x509.AccessDescription(
                    AuthorityInformationAccessOID.CA_ISSUERS,
                    x509.UniformResourceIdentifier(ca_issuer_url),
                )
            ]),
            critical=False,
        )
    return builder.sign(key, hashes.SHA256())


@pytest.fixture(autouse=True)
def _clear_cache():
    # The context cache is per process and these tests reuse hostnames.
    ssl_context_for.cache_clear()
    yield
    ssl_context_for.cache_clear()


@pytest.fixture
def leaf_with_aia(monkeypatch):
    """A server whose leaf points at one missing intermediate."""
    leaf = _certificate("portal.example.gov.in", issuer_name="Example CA",
                        ca_issuer_url=ISSUER_URL)
    monkeypatch.setattr(tls, "_leaf_certificate", lambda host, port: leaf)
    return leaf


def _serve(certificates: dict[str, x509.Certificate], monkeypatch, encoding=Encoding.DER):
    """Stub the intermediate download, recording which URLs were requested."""
    requested: list[str] = []

    def fake_download(url: str):
        requested.append(url)
        cert = certificates.get(url)
        if cert is None:
            raise TLSChainError(f"could not download the intermediate at {url}: 404")
        return [cert]

    monkeypatch.setattr(tls, "_download_certificates", fake_download)
    return requested


class TestChainRepair:
    def test_returns_a_verifying_context(self, leaf_with_aia, monkeypatch):
        _serve({ISSUER_URL: _certificate("Example CA", is_ca=True)}, monkeypatch)

        context = ssl_context_for("portal.example.gov.in")

        assert isinstance(context, ssl.SSLContext)
        # The entire point: the repaired context still verifies.
        assert context.verify_mode == ssl.CERT_REQUIRED
        assert context.check_hostname is True

    def test_loads_the_recovered_intermediate_into_the_trust_store(
        self, leaf_with_aia, monkeypatch
    ):
        intermediate = _certificate("Example CA", is_ca=True)
        _serve({ISSUER_URL: intermediate}, monkeypatch)

        context = ssl_context_for("portal.example.gov.in")

        subjects = [c["subject"] for c in context.get_ca_certs()]
        assert any(
            ("commonName", "Example CA") in [pair for rdn in s for pair in rdn]
            for s in subjects
        ), "the downloaded intermediate should now be trusted"

    def test_keeps_the_public_roots(self, leaf_with_aia, monkeypatch):
        # Adding an intermediate must not replace certifi's roots — without them
        # the recovered certificate chains to nothing.
        _serve({ISSUER_URL: _certificate("Example CA", is_ca=True)}, monkeypatch)

        context = ssl_context_for("portal.example.gov.in")

        assert len(context.get_ca_certs()) > 50

    def test_follows_the_chain_upwards(self, leaf_with_aia, monkeypatch):
        # Two missing links: the intermediate names its own issuer.
        intermediate = _certificate("Example CA", issuer_name="Example Root",
                                    ca_issuer_url=ROOT_URL, is_ca=True)
        root = _certificate("Example Root", is_ca=True)
        requested = _serve({ISSUER_URL: intermediate, ROOT_URL: root}, monkeypatch)

        ssl_context_for("portal.example.gov.in")

        assert requested == [ISSUER_URL, ROOT_URL]

    def test_stops_at_a_self_issued_root(self, leaf_with_aia, monkeypatch):
        root = _certificate("Example CA", is_ca=True)  # subject == issuer
        requested = _serve({ISSUER_URL: root}, monkeypatch)

        ssl_context_for("portal.example.gov.in")

        assert requested == [ISSUER_URL], "nothing sits above a self-issued root"

    def test_a_circular_aia_terminates(self, monkeypatch):
        # A certificate naming itself as its own issuer must not loop forever.
        looping = _certificate("Loop CA", issuer_name="Someone Else",
                               ca_issuer_url=ISSUER_URL, is_ca=True)
        monkeypatch.setattr(tls, "_leaf_certificate", lambda host, port: looping)
        requested = _serve({ISSUER_URL: looping}, monkeypatch)

        ssl_context_for("loop.example.gov.in")

        assert requested == [ISSUER_URL]


class TestRefusalToDowngrade:
    def test_no_aia_extension_returns_none(self, monkeypatch):
        # No AIA means a missing intermediate is not the problem, so there is
        # nothing to repair and the caller must fail loudly.
        bare = _certificate("expired.example.gov.in")
        monkeypatch.setattr(tls, "_leaf_certificate", lambda host, port: bare)

        assert ssl_context_for("expired.example.gov.in") is None

    def test_an_ocsp_only_aia_counts_as_no_ca_issuers(self, monkeypatch):
        # AIA is present but names only an OCSP responder — no issuer to fetch.
        key = _key()
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ocsp.example.gov.in")])
        now = datetime.now(timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(
                x509.AuthorityInformationAccess([
                    x509.AccessDescription(
                        AuthorityInformationAccessOID.OCSP,
                        x509.UniformResourceIdentifier("http://ocsp.example-ca.test"),
                    )
                ]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        monkeypatch.setattr(tls, "_leaf_certificate", lambda host, port: cert)

        assert ssl_context_for("ocsp.example.gov.in") is None

    def test_a_failed_download_raises_rather_than_returning_a_context(
        self, leaf_with_aia, monkeypatch
    ):
        _serve({}, monkeypatch)  # the AIA URL 404s

        with pytest.raises(TLSChainError, match="could not download"):
            ssl_context_for("portal.example.gov.in")

    def test_an_unreachable_host_raises(self, monkeypatch):
        def refuse(host, port):
            raise TLSChainError(f"{host}: could not read the leaf certificate: refused")

        monkeypatch.setattr(tls, "_leaf_certificate", refuse)

        with pytest.raises(TLSChainError):
            ssl_context_for("unreachable.example.gov.in")


class TestCertificateDownload:
    def _response(self, body: bytes, content_type: str = "application/pkix-cert"):
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": content_type},
            request=httpx.Request("GET", ISSUER_URL),
        )

    def test_reads_der(self, monkeypatch):
        cert = _certificate("Example CA", is_ca=True)
        monkeypatch.setattr(
            tls.httpx, "get",
            lambda *a, **k: self._response(cert.public_bytes(Encoding.DER)),
        )
        assert tls._download_certificates(ISSUER_URL)[0].subject == cert.subject

    def test_reads_pem(self, monkeypatch):
        cert = _certificate("Example CA", is_ca=True)
        monkeypatch.setattr(
            tls.httpx, "get",
            lambda *a, **k: self._response(cert.public_bytes(Encoding.PEM)),
        )
        assert tls._download_certificates(ISSUER_URL)[0].subject == cert.subject

    def test_an_html_error_page_is_reported_not_silently_skipped(self, monkeypatch):
        # A CA that has moved its files serves a 200 HTML page. Parsing that as
        # a certificate fails, and the message should say what actually arrived.
        monkeypatch.setattr(
            tls.httpx, "get",
            lambda *a, **k: self._response(b"<html>Not Found</html>", "text/html"),
        )
        with pytest.raises(TLSChainError, match="neither DER nor PEM"):
            tls._download_certificates(ISSUER_URL)


class TestNoDowngradesInTheCodebase:
    """The rule this module exists to enforce, checked mechanically.

    Turning verification off is a one-line change that nothing else catches:
    the scraper starts working, the tests stay green, and the guarantee is gone.
    """

    APP = Path(__file__).resolve().parent.parent / "app"

    def _sources(self):
        return sorted(self.APP.rglob("*.py"))

    def test_no_scraper_disables_certificate_verification(self):
        banned = "verify" + "=False"  # split so this test does not match itself
        offenders = [
            f"{p.relative_to(self.APP)}:{n}"
            for p in self._sources()
            for n, line in enumerate(p.read_text().splitlines(), 1)
            if banned in line
        ]
        assert offenders == [], (
            f"{banned} disables certificate verification entirely. If the chain "
            "is incomplete, repair it with client_aia() instead."
        )

    def test_cert_none_is_confined_to_the_leaf_probe(self):
        # CERT_NONE is legitimate in exactly one place: reading the leaf to find
        # out where its issuer lives. Nothing that probe returns is trusted.
        offenders = {
            str(p.relative_to(self.APP))
            for p in self._sources()
            if "CERT_NONE" in p.read_text()
        }
        assert offenders == {"scrapers/utils/tls.py"}


class TestCaching:
    def test_one_probe_per_host(self, monkeypatch):
        calls: list[str] = []
        leaf = _certificate("cached.example.gov.in", ca_issuer_url=ISSUER_URL)

        def counting_leaf(host, port):
            calls.append(host)
            return leaf

        monkeypatch.setattr(tls, "_leaf_certificate", counting_leaf)
        _serve({ISSUER_URL: _certificate("Example CA", is_ca=True)}, monkeypatch)

        first = ssl_context_for("cached.example.gov.in")
        second = ssl_context_for("cached.example.gov.in")

        assert first is second
        assert calls == ["cached.example.gov.in"]
