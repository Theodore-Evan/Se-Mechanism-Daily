from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.collect_papers import (
    Topic,
    arxiv_query,
    attach_best_match,
    canonical_key,
    collect,
    deduplicate,
    parse_config,
    parse_datetime,
    reconstruct_abstract,
    scholar_year,
)


class ConfigurationTests(unittest.TestCase):
    def test_parses_selenium_topics_and_sources(self) -> None:
        sources, topics = parse_config(
            {
                "sources": [{"type": "pubmed", "name": "PubMed"}],
                "topics": [
                    {
                        "id": "selenoproteins",
                        "name": "硒蛋白",
                        "description": "硒蛋白生物合成",
                        "keywords": ["selenoprotein", "selenocysteine"],
                        "arxiv_categories": ["q-bio.BM"],
                    }
                ],
            }
        )
        self.assertEqual(sources[0].type, "pubmed")
        self.assertEqual(topics[0].keywords, ["selenoprotein", "selenocysteine"])

    def test_rejects_empty_topics(self) -> None:
        with self.assertRaises(ValueError):
            parse_config({"sources": [{"type": "pubmed", "name": "PubMed"}], "topics": []})

    def test_arxiv_query_uses_keywords_without_category_noise_by_default(self) -> None:
        topic = Topic("redox", "氧化还原", "", ["selenium ferroptosis", "GPX4"], ["q-bio.BM"])
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARXIV_EXPAND_CATEGORY_SEARCH", None)
            query = arxiv_query(topic)
        self.assertIn('all:"selenium ferroptosis"', query)
        self.assertNotIn("cat:q-bio.BM", query)


class NormalizationTests(unittest.TestCase):
    def test_parse_datetime_accepts_year_only(self) -> None:
        self.assertEqual(parse_datetime("2026").date().isoformat(), "2026-01-01")

    def test_reconstructs_openalex_abstract(self) -> None:
        abstract = reconstruct_abstract({"Selenium": [0], "controls": [1], "GPX4": [2]})
        self.assertEqual(abstract, "Selenium controls GPX4")

    def test_extracts_scholar_year(self) -> None:
        self.assertEqual(
            scholar_year({"publication_info": {"summary": "A Author - Redox Biology, 2026 - Elsevier"}}),
            "2026",
        )

    def test_deduplicates_by_title_and_merges_sources(self) -> None:
        papers = deduplicate(
            [
                {"id": "pubmed:1", "source": "PubMed", "title": "Selenium and GPX4", "authors": [], "categories": []},
                {
                    "id": "openalex:w1",
                    "source": "OpenAlex",
                    "title": "Selenium & GPX4",
                    "summary": "A detailed abstract.",
                    "authors": [],
                    "categories": [],
                },
            ]
        )
        self.assertEqual(len(papers), 1)
        self.assertIn("PubMed", papers[0]["source"])
        self.assertIn("OpenAlex", papers[0]["source"])

    def test_doi_is_preferred_as_canonical_key(self) -> None:
        self.assertEqual(canonical_key({"doi": "10.1000/ABC", "id": "source:1"}), "doi:10.1000/abc")


class ScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.topic = Topic(
            "ferroptosis",
            "硒与铁死亡",
            "硒、GPX4 和脂质过氧化",
            ["selenium ferroptosis", "GPX4", "lipid peroxidation"],
            ["q-bio.BM"],
        )

    def test_title_and_abstract_hits_produce_relevant_match(self) -> None:
        paper = attach_best_match(
            [self.topic],
            {
                "title": "Selenium regulation of GPX4 in ferroptosis",
                "summary": "The study measures GPX4 and lipid peroxidation.",
                "categories": [],
            },
        )
        self.assertGreaterEqual(paper["best_match"]["score"], 0.3)
        self.assertEqual(paper["best_match"]["topic_id"], "ferroptosis")

    def test_unrelated_paper_has_zero_score(self) -> None:
        paper = attach_best_match(
            [self.topic],
            {"title": "Marine ecology field observations", "summary": "", "categories": []},
        )
        self.assertEqual(paper["best_match"]["score"], 0)


class CollectionTests(unittest.TestCase):
    def test_collection_isolates_source_failure_and_writes_public_schema(self) -> None:
        config = {
            "sources": [
                {"type": "pubmed", "name": "PubMed"},
                {"type": "openalex", "name": "OpenAlex"},
            ],
            "topics": [
                {
                    "id": "selenium",
                    "name": "硒代谢",
                    "description": "硒代谢机制",
                    "keywords": ["selenium metabolism"],
                    "arxiv_categories": [],
                }
            ],
        }
        paper = {
            "id": "pubmed:123",
            "source": "PubMed",
            "title": "Selenium metabolism in mammalian cells",
            "summary": "This article studies selenium metabolism.",
            "authors": ["Researcher A"],
            "published": "2026-07-29",
            "updated": "2026-07-29",
            "categories": [],
            "paper_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
            "pdf_url": "",
        }
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            output_path = Path(directory) / "papers.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with (
                mock.patch("scripts.collect_papers.utc_now") as mocked_now,
                mock.patch("scripts.collect_papers.SOURCE_FETCHERS") as fetchers,
                mock.patch.dict(os.environ, {"SOURCE_DELAY_SECONDS": "0", "MIN_DAILY_PAPERS": "0"}, clear=False),
            ):
                mocked_now.return_value = parse_datetime("2026-07-30T00:00:00Z")
                fetchers.get.side_effect = [lambda _topic, _limit: [paper], lambda _topic, _limit: (_ for _ in ()).throw(RuntimeError("temporary"))]
                payload = collect(
                    config_path,
                    output_path,
                    lookback_days=7,
                    max_per_topic=5,
                    max_summaries=0,
                    clear_cache=True,
                )
        self.assertEqual(payload["data_kind"], "selenium_mechanism")
        self.assertEqual(payload["stats"]["paper_count"], 1)
        self.assertEqual(payload["stats"]["source_stats"][1]["status"], "failed")
        self.assertNotIn("conference", json.dumps(payload).lower())


if __name__ == "__main__":
    unittest.main()
