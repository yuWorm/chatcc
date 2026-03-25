"""AES-128-ECB encryption for WeChat CDN media files."""

from __future__ import annotations

import base64
import binascii
import os
import re

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

_HEX_32 = re.compile(r"^[0-9a-fA-F]{32}$")


class CryptoError(Exception):
    pass


def encrypt_aes_ecb(plaintext: bytes, key: bytes) -> bytes:
    if len(key) != 16:
        raise CryptoError(f"AES key must be 16 bytes, got {len(key)}")
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return enc.update(padded) + enc.finalize()


def decrypt_aes_ecb(ciphertext: bytes, key: bytes) -> bytes:
    if len(key) != 16:
        raise CryptoError(f"AES key must be 16 bytes, got {len(key)}")
    if len(ciphertext) % 16 != 0:
        raise CryptoError(f"Ciphertext length {len(ciphertext)} is not a multiple of 16")
    dec = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = dec.update(ciphertext) + dec.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def generate_aes_key() -> bytes:
    return os.urandom(16)


def decode_aes_key(encoded: str) -> bytes:
    """Decode an aes_key from the protocol.

    Handles three formats:
      - Direct hex string (32 hex chars)
      - base64(raw 16 bytes)
      - base64(hex string 32 chars)
    """
    if _HEX_32.match(encoded):
        return binascii.unhexlify(encoded)

    try:
        decoded = base64.b64decode(encoded)
    except Exception as e:
        raise CryptoError(f"Cannot base64 decode aes_key: {e}") from e

    if len(decoded) == 16:
        return decoded

    if len(decoded) == 32:
        try:
            hex_str = decoded.decode("ascii")
            if _HEX_32.match(hex_str):
                return binascii.unhexlify(hex_str)
        except (UnicodeDecodeError, binascii.Error):
            pass

    raise CryptoError(f"Decoded aes_key has unexpected length {len(decoded)} (want 16 or 32)")


def encode_aes_key_hex(key: bytes) -> str:
    return key.hex()


def encode_aes_key_base64(key: bytes) -> str:
    return base64.b64encode(key.hex().encode("utf-8")).decode("ascii")
