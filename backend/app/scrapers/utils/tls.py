"""Repairing incomplete TLS certificate chains, without disabling verification.

Several government portals serve only their leaf certificate and omit the
intermediate that links it to a trusted root. The root itself is legitimate and
already in every trust store — GlobalSign for `ibps.in`, Let's Encrypt for
`egazette.gov.in` — so these are misconfigured servers, not untrustworthy ones.
Browsers paper over it by following the leaf's Authority Information Access
"CA Issuers" URI and downloading the missing piece. Python does not, so the
handshake fails with `unable to get local issuer certificate`.

`ssl_context_for(host)` does what the browser does: read the leaf, follow its
AIA URI, and hand back a context holding certifi's roots *plus* the recovered
intermediates. Verification stays fully on — the repaired context still checks
hostnames and still requires a chain to a trusted root.

The temptation this module exists to remove is switching verification off. That
accepts any certificate from anyone, which on a public listing page looks
harmless right up until the day someone is in the middle of the connection.
Repairing the chain costs one cached round trip and keeps the guarantee.
`test_no_scraper_disables_certificate_verification` enforces the rule.

Returns `None` when the certificate carries no AIA URI at all: that host's
problem is something else — an expired certificate, or a name mismatch like
RRB Chandigarh's — and callers must fail loudly rather than downgrade.
"""

from __future__ import annotations

import logging
import socket
import ssl
from functools import lru_cache

import certifi
import httpx
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID

log = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT = 15.0
DOWNLOAD_TIMEOUT = 15.0

#: How far up the chain to chase. One missing intermediate is the normal case;
#: the cap stops a misconfigured or circular AIA sending us round forever.
MAX_CHAIN_DEPTH = 4


class TLSChainError(RuntimeError):
    """The chain is incomplete and could not be repaired.

    Raised rather than returning a context so that no caller can mistake a
    failed repair for a successful one and continue unverified.
    """


@lru_cache(maxsize=32)
def ssl_context_for(host: str, port: int = 443) -> ssl.SSLContext | None:
    """A verifying SSL context that includes the intermediates `host` omits.

    Returns `None` if the leaf names no CA Issuers URI, meaning this is not a
    missing-intermediate problem and there is nothing here to fix. Raises
    `TLSChainError` if the URI is there but the repair fails.

    Cached per host: the probe and download happen once per process.
    """
    leaf = _leaf_certificate(host, port)
    pending = _ca_issuer_urls(leaf)
    if not pending:
        log.warning(
            "%s: certificate names no AIA caIssuers URI, so a missing "
            "intermediate is not the problem here", host
        )
        return None

    context = ssl.create_default_context(cafile=certifi.where())
    seen: set[str] = set()
    added = 0

    for _ in range(MAX_CHAIN_DEPTH):
        if not pending:
            break
        url = pending.pop(0)
        if url in seen:
            continue
        seen.add(url)

        for cert in _download_certificates(url):
            context.load_verify_locations(
                cadata=cert.public_bytes(Encoding.PEM).decode("ascii")
            )
            added += 1
            # A self-issued certificate is a root; there is nothing above it.
            if cert.subject != cert.issuer:
                pending.extend(u for u in _ca_issuer_urls(cert) if u not in seen)

    log.info("%s: recovered %d intermediate certificate(s) via AIA", host, added)
    return context


def _leaf_certificate(host: str, port: int) -> x509.Certificate:
    """Read the server's leaf certificate without validating it.

    This connection is deliberately unverified, and that is safe because
    nothing it returns is trusted. It is used only to discover *where the
    issuer lives*. Whatever intermediate that URI points at still has to chain
    to a certifi root during the real handshake, so tampering with this probe
    yields a certificate that fails verification — not a way past it.
    """
    probe = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    probe.check_hostname = False
    probe.verify_mode = ssl.CERT_NONE

    try:
        with socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT) as sock:
            with probe.wrap_socket(sock, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except OSError as exc:
        raise TLSChainError(f"{host}: could not read the leaf certificate: {exc}") from exc

    if not der:
        raise TLSChainError(f"{host}: server presented no certificate")
    return x509.load_der_x509_certificate(der)


def _ca_issuer_urls(cert: x509.Certificate) -> list[str]:
    """The http(s) CA Issuers URIs named by a certificate's AIA extension."""
    try:
        aia = cert.extensions.get_extension_for_class(
            x509.AuthorityInformationAccess
        ).value
    except x509.ExtensionNotFound:
        return []

    return [
        access.access_location.value
        for access in aia
        if access.access_method == AuthorityInformationAccessOID.CA_ISSUERS
        and isinstance(access.access_location, x509.UniformResourceIdentifier)
    ]


def _download_certificates(url: str) -> list[x509.Certificate]:
    """Fetch the intermediate an AIA URI points at.

    These URIs are plain HTTP by convention, and that is fine: the certificate
    is trusted because it chains to a root we already hold, not because of how
    it arrived. Serving a forged one changes nothing — it simply fails to
    verify.

    CAs serve DER or PEM. A CA serving PKCS#7 will land in the error below
    rather than being guessed at.
    """
    try:
        response = httpx.get(url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise TLSChainError(f"could not download the intermediate at {url}: {exc}") from exc

    body = response.content
    for load in (x509.load_der_x509_certificate, x509.load_pem_x509_certificate):
        try:
            return [load(body)]
        except ValueError:
            continue

    content_type = response.headers.get("content-type", "unknown")
    raise TLSChainError(
        f"{url} returned {len(body)} bytes of {content_type}, which is neither "
        "DER nor PEM; the chain cannot be repaired from it"
    )
