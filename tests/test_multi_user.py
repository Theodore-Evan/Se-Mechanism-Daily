from __future__ import annotations

import base64
import os
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts.collect_users import decrypt_credentials, normalize_research_map


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


class ResearchMapTests(unittest.TestCase):
    def test_research_map_tables_are_account_isolated(self) -> None:
        migration = (ROOT / "supabase" / "migrations" / "202609300001_ai_research_maps.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.user_research_maps", migration)
        self.assertIn("create table if not exists public.research_map_requests", migration)
        self.assertIn("enable row level security", migration)
        self.assertIn("(select auth.uid()) = user_id", migration)
        self.assertNotIn("grant insert on table public.user_research_maps", migration)

    def test_model_cannot_reference_unstarred_papers(self) -> None:
        source = [{"paper_id": "kept", "title": "Input paper"}]
        raw = {
            "title": "Map", "thesis": "Thesis", "root": {"name": "Root", "description": "Desc"},
            "branches": [{
                "id": "redox", "name": "Redox", "focus": "Focus", "priority": "core",
                "papers": [
                    {"paper_id": "kept", "title": "Input paper", "year": 2025, "role": "evidence", "finding": "finding", "evidence": "abstract", "connection": "root", "methods": ["assay"], "models": ["cells"], "mechanisms": ["ROS"]},
                    {"paper_id": "invented", "title": "Invented", "year": 2024},
                ],
            }],
            "cross_links": [], "research_gaps": [], "next_questions": [],
        }
        result = normalize_research_map(raw, source)
        self.assertEqual([paper["paper_id"] for paper in result["branches"][0]["papers"]], ["kept"])

    def test_frontend_renders_timeline_and_queues_ai_map(self) -> None:
        script = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        backend = (ROOT / "web" / "backend.js").read_text(encoding="utf-8")
        self.assertIn("function renderResearchMapGraphic", script)
        self.assertIn("AI 构建研究体系", script)
        self.assertIn("queueResearchMap", backend)


if __name__ == "__main__":
    unittest.main()
