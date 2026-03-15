"""
Kalshi API authentication via RSA-PSS signatures.

Every authenticated request requires three headers:
  KALSHI-ACCESS-KEY:       API key ID
  KALSHI-ACCESS-TIMESTAMP: Unix milliseconds
  KALSHI-ACCESS-SIGNATURE: RSA-PSS signature (base64)

Signature message: "{timestamp_ms}{HTTP_METHOD}{path_without_query}"
Algorithm: RSASSA-PSS with SHA-256, MGF1(SHA-256), salt_length=DIGEST_LENGTH
"""

from __future__ import annotations

import base64
import time
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def load_private_key(pem_path: str) -> rsa.RSAPrivateKey:
    """Load an RSA private key from a PEM file."""
    key_bytes = Path(pem_path).read_bytes()
    private_key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise TypeError(f"Expected RSA private key, got {type(private_key).__name__}")
    return private_key


def sign_request(
    private_key: rsa.RSAPrivateKey,
    method: str,
    path: str,
    timestamp_ms: int | None = None,
) -> tuple[str, str]:
    """
    Sign a Kalshi API request.

    Returns:
        (base64_signature, timestamp_ms_string)
    """
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    # Strip query string from path before signing
    path_no_query = path.split("?")[0]

    message = f"{timestamp_ms}{method.upper()}{path_no_query}".encode("utf-8")

    signature_bytes = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )

    signature_b64 = base64.b64encode(signature_bytes).decode("utf-8")
    return signature_b64, str(timestamp_ms)


def build_auth_headers(
    api_key_id: str,
    private_key: rsa.RSAPrivateKey,
    method: str,
    path: str,
    timestamp_ms: int | None = None,
) -> dict[str, str]:
    """Build the three authentication headers for a Kalshi API request."""
    signature, ts_str = sign_request(private_key, method, path, timestamp_ms)
    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": ts_str,
    }
