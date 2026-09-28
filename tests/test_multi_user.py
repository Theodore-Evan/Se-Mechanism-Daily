from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.collect_users import decrypt_credentials


ROOT = Path(__file__).resolve().parents[1]


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


class StarredPaperMigrationTests(unittest.TestCase):
    def test_starred_papers_are_account_isolated_snapshots(self) -> None:
        migration = (ROOT / "supabase" / "migrations" / "202609280001_starred_papers.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.user_starred_papers", migration)
        self.assertIn("payload jsonb not null", migration)
        self.assertIn("enable row level security", migration)
        self.assertIn("(select auth.uid()) = user_id", migration)
        self.assertNotIn("references public.user_papers", migration)

    def test_frontend_exposes_star_and_mind_tree_controls(self) -> None:
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn('data-view="starred"', html)
        self.assertIn('class="star-button"', html)
        self.assertIn("function renderStarTree()", script)
        self.assertIn("backend.setStarredPaper", script)


if __name__ == "__main__":
    unittest.main()
