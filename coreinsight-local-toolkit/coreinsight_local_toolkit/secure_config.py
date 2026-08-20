"""Small build-in configuration decoder.

The same machine environment variable is required on every installation.  The
values below are not plaintext credentials; the runtime key is never stored in
the package.  This is obfuscation plus tamper detection, not a replacement for
OS credential storage when a stronger threat model is required.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os


_PACKAGED = {
    "clouddrive_account": "QSxZqknFuTlqDKKlo0crT4aKfZeJ1n61Q-apF2JNy1-sn1I_lENVNWZoxj5i",
    "clouddrive_password": "5jgXKo6F0uYKtYE6dPVA1hupbzKFNhGivglxTkwswhm6j9ou5BikUZ8JSb8=",
    "hermes_api_key": "I5DOPiIww5IxHiiLG9xLl8-UpagS_WtSrpsDrw-ecOnI2VhZuQCHhsKIPwkuRkl6dqteoWQ2BQ==",
}


def _decrypt(value: str, key: bytes) -> str:
    raw = base64.urlsafe_b64decode(value.encode("ascii"))
    nonce, ciphertext, tag = raw[:16], raw[16:-16], raw[-16:]
    expected = hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected):
        raise RuntimeError("内置配置校验失败")
    stream = bytearray()
    counter = 0
    while len(stream) < len(ciphertext):
        stream.extend(hmac.new(
            key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(ciphertext, stream)).decode("utf-8")


def packaged_config() -> dict[str, str]:
    master = os.getenv("COREINSIGHT_DRAFT_DB_USER", "").strip()
    if not master:
        return {}
    key = hashlib.sha256(master.encode("utf-8")).digest()
    return {name: _decrypt(value, key) for name, value in _PACKAGED.items()}
