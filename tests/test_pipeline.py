import json
import tempfile
import unittest
from pathlib import Path

from knowledgeflow.pipeline import (
    Store,
    append_jsonl,
    canonical_url,
    health,
    keyword_matches,
    load_jsonl,
    parse_feed,
    promote,
    render_dashboard,
    score_item,
)


CONFIG = {
    "schema_version": 1,
    "project_name": "Test",
    "inbox_note": "20-inbox/00-dashboard.md",
    "home_note": "00-home.md",
    "knowledge_root": "10-kb",
    "policy": {
        "min_score": 60,
        "min_summary_chars": 30,
        "max_age_days": 730,
        "max_items_per_source": 8,
        "max_promotions_per_run": 24,
    },
    "topics": [
        {"id": "ai", "title": "AI", "directory": "10-kb/ai", "keywords": ["agent", "ai"]},
        {"id": "general", "title": "General", "directory": "10-kb/general", "keywords": []},
    ],
    "sources": [
        {"id": "official", "title": "Official feed", "url": "https://example.test/feed.xml", "authority": "Example Authority", "tier": "A", "active": True, "topics": ["ai"], "tags": ["official"]}
    ],
}


class PipelineTest(unittest.TestCase):
    def make_store(self):
        temp = tempfile.TemporaryDirectory()
        vault = Path(temp.name)
        config_file = vault / ".knowledgeflow/config.json"
        config_file.parent.mkdir(parents=True)
        config_file.write_text(json.dumps(CONFIG), "utf-8")
        return temp, Store(vault)

    def candidate(self):
        return {
            "id": "ki-0123456789abcdef",
            "status": "pending",
            "title": "A practical AI agent evaluation framework",
            "url": "https://example.test/research/agent-evaluation",
            "summary": "A sufficiently detailed source summary explaining the evaluation framework and its intended use.",
            "published_at": "2026-07-20",
            "discovered_at": "2026-07-22T00:00:00+00:00",
            "source_id": "official",
            "source_title": "Official feed",
            "source_authority": "Example Authority",
            "source_tier": "A",
            "topic_id": "ai",
            "topic_title": "AI",
            "topic_directory": "10-kb/ai",
            "tags": ["official"],
            "quality": {"overall": 91.0, "authority": 100, "relevance": 90, "freshness": 100, "structured": 88, "keyword_hits": ["agent", "ai"]},
        }

    def test_canonical_url_removes_tracking_and_fragment(self):
        self.assertEqual(
            canonical_url("HTTPS://Example.COM/a/?utm_source=x&keep=1#part"),
            "https://example.com/a?keep=1",
        )

    def test_parse_rss_and_atom(self):
        rss = b"""<rss><channel><item><title>AI update</title><link>https://example.test/a</link><description>Useful &amp; structured summary</description><pubDate>Mon, 20 Jul 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
        atom = b"""<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Agent paper</title><link href='/paper'/><summary>New research</summary><updated>2026-07-21T12:00:00Z</updated></entry></feed>"""
        self.assertEqual(parse_feed(rss)[0]["title"], "AI update")
        self.assertEqual(parse_feed(atom, "https://example.test/feed")[0]["url"], "https://example.test/paper")

    def test_score_is_bounded_and_explained(self):
        item = {"title": "AI agent", "summary": "x" * 200, "url": "https://example.test/a", "published_at": "2026-07-20"}
        result = score_item(item, CONFIG["sources"][0], ["ai", "agent"], CONFIG)
        self.assertGreaterEqual(result["overall"], 60)
        self.assertLessEqual(result["overall"], 100)
        self.assertEqual(result["keyword_hits"], ["ai", "agent"])

    def test_short_ascii_keyword_uses_word_boundaries(self):
        self.assertTrue(keyword_matches("AI agent systems", "ai"))
        self.assertFalse(keyword_matches("differential equations", "ai"))
        self.assertTrue(keyword_matches("智能体工程", "智能体"))

    def test_promote_numbers_routes_and_never_reflows(self):
        temp, store = self.make_store()
        self.addCleanup(temp.cleanup)
        append_jsonl(store.data / "candidates.jsonl", [self.candidate()])
        first = promote(store)
        self.assertEqual(first["promoted"], 1)
        relative = Path(first["items"][0]["path"])
        self.assertTrue(relative.name.startswith("001-2026-07-20-"))
        note = store.vault / relative
        text = note.read_text("utf-8")
        self.assertIn("auto_ingested: true", text)
        self.assertIn("candidate_id:", text)
        self.assertIn("自动入库 · 待抽检", text)
        note.unlink()
        second = promote(store)
        self.assertEqual(second["promoted"], 0)
        self.assertFalse(note.exists())
        self.assertEqual(len(load_jsonl(store.data / "decisions.jsonl")), 1)

    def test_dashboard_and_health_contract(self):
        temp, store = self.make_store()
        self.addCleanup(temp.cleanup)
        append_jsonl(store.data / "candidates.jsonl", [self.candidate()])
        promote(store)
        status = render_dashboard(store)
        report = health(store)
        self.assertEqual(status["published"], 1)
        self.assertTrue(report["healthy"])
        self.assertEqual(report["generated_notes"], 1)
        self.assertTrue((store.vault / CONFIG["inbox_note"]).exists())

    def test_broad_source_requires_topic_keyword(self):
        temp, store = self.make_store()
        self.addCleanup(temp.cleanup)
        config = store.config()
        config["sources"][0]["require_keyword"] = True
        store.config_file.write_text(json.dumps(config), "utf-8")
        candidate = self.candidate()
        candidate["quality"]["keyword_hits"] = []
        append_jsonl(store.data / "candidates.jsonl", [candidate])
        result = promote(store, dry_run=True)
        self.assertEqual(result["promoted"], 0)
        self.assertEqual(result["rejected"], 1)
        self.assertIn("required-topic-keyword-missing", result["rejected_items"][0]["reasons"])

    def test_dry_run_simulates_sequential_numbers(self):
        temp, store = self.make_store()
        self.addCleanup(temp.cleanup)
        first = self.candidate()
        second = self.candidate()
        second["id"] = "ki-fedcba9876543210"
        second["url"] = "https://example.test/research/second"
        second["title"] = "A second AI agent framework"
        append_jsonl(store.data / "candidates.jsonl", [first, second])
        result = promote(store, dry_run=True)
        names = [Path(item["path"]).name for item in result["items"]]
        self.assertTrue(names[0].startswith("001-"))
        self.assertTrue(names[1].startswith("002-"))


if __name__ == "__main__":
    unittest.main()
