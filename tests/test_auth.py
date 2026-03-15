"""Tests for Kalshi API authentication."""

import base64
import tempfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from engine.api.auth import build_auth_headers, load_private_key, sign_request


@pytest.fixture
def rsa_key_pair():
    """Generate a test RSA key pair."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    return private_key


@pytest.fixture
def pem_file(rsa_key_pair):
    """Write the private key to a temporary PEM file."""
    pem_bytes = rsa_key_pair.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False) as f:
        f.write(pem_bytes)
        return f.name


def test_load_private_key(pem_file):
    key = load_private_key(pem_file)
    assert isinstance(key, rsa.RSAPrivateKey)


def test_sign_request_returns_tuple(rsa_key_pair):
    sig, ts = sign_request(rsa_key_pair, "GET", "/trade-api/v2/portfolio/balance", 1703123456789)
    assert isinstance(sig, str)
    assert ts == "1703123456789"
    # Signature should be valid base64
    base64.b64decode(sig)


def test_signature_is_verifiable(rsa_key_pair):
    timestamp_ms = 1703123456789
    method = "GET"
    path = "/trade-api/v2/portfolio/balance"

    sig_b64, _ = sign_request(rsa_key_pair, method, path, timestamp_ms)
    sig_bytes = base64.b64decode(sig_b64)

    message = f"{timestamp_ms}{method}{path}".encode("utf-8")
    public_key = rsa_key_pair.public_key()

    # Should not raise — valid signature
    public_key.verify(
        sig_bytes,
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )


def test_query_string_stripped_from_signature(rsa_key_pair):
    sig_with_query, _ = sign_request(
        rsa_key_pair, "GET", "/trade-api/v2/markets?status=open", 1703123456789
    )
    sig_without_query, _ = sign_request(
        rsa_key_pair, "GET", "/trade-api/v2/markets", 1703123456789
    )
    # Both should produce the same signature (same message after stripping query)
    # Note: RSA-PSS is probabilistic, so signatures differ even for same input.
    # Instead, verify both are valid against the stripped path.
    message = f"1703123456789GET/trade-api/v2/markets".encode("utf-8")
    public_key = rsa_key_pair.public_key()

    for sig_b64 in [sig_with_query, sig_without_query]:
        public_key.verify(
            base64.b64decode(sig_b64),
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )


def test_build_auth_headers(rsa_key_pair):
    headers = build_auth_headers(
        api_key_id="test-key-123",
        private_key=rsa_key_pair,
        method="POST",
        path="/trade-api/v2/portfolio/orders",
    )
    assert headers["KALSHI-ACCESS-KEY"] == "test-key-123"
    assert "KALSHI-ACCESS-SIGNATURE" in headers
    assert "KALSHI-ACCESS-TIMESTAMP" in headers
    # Timestamp should be a numeric string
    int(headers["KALSHI-ACCESS-TIMESTAMP"])


def test_different_methods_different_signatures(rsa_key_pair):
    sig_get, _ = sign_request(
        rsa_key_pair, "GET", "/trade-api/v2/markets", 1703123456789
    )
    sig_post, _ = sign_request(
        rsa_key_pair, "POST", "/trade-api/v2/markets", 1703123456789
    )
    # PSS is probabilistic, but we can verify each against the correct message
    public_key = rsa_key_pair.public_key()

    public_key.verify(
        base64.b64decode(sig_get),
        b"1703123456789GET/trade-api/v2/markets",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
    public_key.verify(
        base64.b64decode(sig_post),
        b"1703123456789POST/trade-api/v2/markets",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
        hashes.SHA256(),
    )
