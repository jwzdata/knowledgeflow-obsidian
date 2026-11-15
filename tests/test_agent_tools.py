"""Offline regression tests for KnowledgeFlow 2.0 agent tools."""

import json
import tempfile
import unittest
from pathlib import Path

from knowledgeflow.agent_tools import (
    build_hot_cache,
    challenge_proposal,
    context_pack,
    crosslink_vault,
    search_vault,
)
from knowledgeflow.pipeline import Store

TEST_CONFIG = {
    "schema_version": 1,
    "project_name": "Agent Test Vault",
    "inbox_note": "20-知识流入/00-流水线收件箱.md",
    "hot_cache_note": "00-导航/01-智能体热启动上下文.md",
    "home_note": "00-导航/00-首页.md",
    "knowledge_root": "10-知识库",
    "synonyms": [
        {"terms": ["碳关税"], "expansions": ["cbam"]},
    ],
    "entity_anchors": [
        {"keywords": ["cbam", "碳关税"], "target": "10-知识库/02-经济与政策/001-CBAM"},
        {"keywords": ["adr", "红线"], "target": "10-知识库/03-架构决策/001-ADR"},
    ],
    "policy": {"min_score": 60, "min_summary_chars": 30},
    "topics": [
        {"id": "ai", "title": "AI", "directory": "10-知识库/01-AI与工程", "keywords": ["agent", "rag"]},
        {"id": "econ", "title": "Economy", "directory": "10-知识库/02-经济与政策", "keywords": ["cbam", "carbon"]},
    ],
    "sources": [
        {"id": "official", "title": "Official Feed", "url": "https://example.test/feed.xml", "authority": "Test", "tier": "A", "active": True, "topics": ["ai"]},
    ],
}


class AgentToolsTests(unittest.TestCase):
    def make_vault(self):
        tmp = tempfile.TemporaryDirectory()
        vault = Path(tmp.name)
        cfg_path = vault / ".knowledgeflow/config.json"
        cfg_path.parent.mkdir(parents=True)
        cfg_path.write_text(json.dumps(TEST_CONFIG), "utf-8")

        (vault / "10-知识库/01-AI与工程").mkdir(parents=True)
        (vault / "10-知识库/02-经济与政策").mkdir(parents=True)
        (vault / "10-知识库/03-架构决策").mkdir(parents=True)
        (vault / "00-导航").mkdir(parents=True)

        (vault / "10-知识库/01-AI与工程/000-知识地图.md").write_text(
            "---\ntype: moc\n---\n# AI MOC\n[[10-知识库/01-AI与工程/001-RAG]]\n",
            "utf-8",
        )
        (vault / "10-知识库/01-AI与工程/001-RAG.md").write_text(
            '---\nid: "n1"\ntitle: "Hybrid RAG Architecture"\nsummary: "BM25 hybrid search and context packing with CBAM compliance notes."\ntype: "domain"\nstatus: "active"\nrag_priority: "primary"\ncontent_updated: "2026-11-15"\n---\n# Hybrid RAG\nUses [[10-知识库/03-架构决策/001-ADR]] to avoid draft leaks.\n\n'
            + ("Hybrid retrieval combines lexical precision, bilingual synonym bridges, and token-bounded evidence packing.\n" * 12),
            "utf-8",
        )
        (vault / "10-知识库/01-AI与工程/002-Draft.md").write_text(
            '---\nid: "n2"\ntitle: "Unpublished Draft Secret"\nsummary: "Should never appear in RAG search results."\ntype: "domain"\nstatus: "draft"\nrag_priority: "primary"\n---\n# Draft\nSecret draft CBAM text.\n',
            "utf-8",
        )
        (vault / "10-知识库/02-经济与政策/001-CBAM.md").write_text(
            '---\nid: "n3"\ntitle: "EU CBAM Carbon Pricing"\nsummary: "Carbon border adjustment rules."\ntype: "domain"\nstatus: "needs-verification"\nrag_priority: "secondary"\nas_of: "2026-08-18"\n---\n# EU CBAM\nEU CBAM import declaration formula.\n',
            "utf-8",
        )
        (vault / "10-知识库/03-架构决策/001-ADR.md").write_text(
            '---\nid: "adr-1"\ntitle: "ADR-001 Draft Isolation"\nsummary: "Never expose draft notes in RAG; warn on unverified CBAM metrics."\ntype: "decision"\nstatus: "active"\nrag_priority: "primary"\ntags: ["ADR", "红线"]\n---\n# ADR-001\nCompliance red line against unverified estimates.\n',
            "utf-8",
        )
        return tmp, Store(vault)

    def test_search_uses_bilingual_synonyms_and_isolates_drafts(self):
        tmp, store = self.make_vault()
        self.addCleanup(tmp.cleanup)

        res = search_vault(store, "碳关税", limit=5)
        sources = [r["source"] for r in res["results"]]
        self.assertIn("10-知识库/02-经济与政策/001-CBAM.md", sources)
        self.assertNotIn("10-知识库/01-AI与工程/002-Draft.md", sources)
        cbam_hit = next(r for r in res["results"] if r["source"].endswith("001-CBAM.md"))
        self.assertIn("待核验", cbam_hit["quality_labels"])

    def test_context_pack_respects_budget_and_compresses(self):
        tmp, store = self.make_vault()
        self.addCleanup(tmp.cleanup)
        res = context_pack(store, "Hybrid RAG", budget=1500, limit=5)
        self.assertGreaterEqual(res["packed_count"], 1)
        self.assertLessEqual(res["used_chars"], 1500)
        self.assertLess(res["compression_ratio"], 1.0)

    def test_challenge_surfaces_adr_and_warnings(self):
        tmp, store = self.make_vault()
        self.addCleanup(tmp.cleanup)
        res = challenge_proposal(store, "接入 CBAM 财务核算并忽略 draft 隔离", limit=5)
        sources = [x["source"] for x in res["items"]]
        self.assertIn("10-知识库/03-架构决策/001-ADR.md", sources)

    def test_crosslink_preview_and_apply_across_folders(self):
        tmp, store = self.make_vault()
        self.addCleanup(tmp.cleanup)
        preview = crosslink_vault(store, apply=False)
        self.assertEqual(preview["changed_files"], 0)
        self.assertGreaterEqual(preview["candidates"], 1)
        applied = crosslink_vault(store, apply=True)
        self.assertGreaterEqual(applied["changed_files"], 1)
        rag_text = (store.vault / "10-知识库/01-AI与工程/001-RAG.md").read_text("utf-8")
        self.assertIn("[[10-知识库/02-经济与政策/001-CBAM]]", rag_text)

    def test_hot_cache_excludes_moc_hubs_and_counts_semantic_edges(self):
        tmp, store = self.make_vault()
        self.addCleanup(tmp.cleanup)
        report = build_hot_cache(store)
        self.assertEqual(report["semantic_edges"], 1)
        content = (store.vault / "00-导航/01-智能体热启动上下文.md").read_text("utf-8")
        self.assertNotIn("AI MOC", content)
        self.assertIn("Hybrid RAG Architecture", content)


if __name__ == "__main__":
    unittest.main()
