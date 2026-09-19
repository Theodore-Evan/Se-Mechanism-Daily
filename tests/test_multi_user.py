from __future__ import annotations

import base64
import os
import unittest

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.collect_users import decrypt_credentials


class CredentialEncryptionTests(unittest.TestCase):
    def test_edge_function_ciphertext_format_is_decryptable_by_collector(self) -> None:
        key = os.urandom(32)
        iv = os.urandom(12)
        encrypted = AESGCM(key).encrypt(iv, b"private-test-key", None)
        rows = [
            {
                "provider": "zhipu",
                "iv": base64.b64encode(iv).decode("ascii"),
                "ciphertext": base64.b64encode(encrypted).decode("ascii"),
            }
        ]
        credentials = decrypt_credentials(rows, base64.b64encode(key).decode("ascii"))
        self.assertEqual(credentials["zhipu"], "private-test-key")

    def test_master_key_must_be_256_bits(self) -> None:
        with self.assertRaises(ValueError):
            decrypt_credentials([], base64.b64encode(b"too-short").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
