from pathlib import Path
import json
import tempfile
import unittest

from llm_wiki.builder import build_wiki, validate_inputs
from llm_wiki.ingest import ingest_statement, load_payload_from_json
from llm_wiki.importer import ImportOptions, import_batch
from llm_wiki.topic_autotag import autotag_source
from llm_wiki.wiki_backend import WikiBackend


class EndToEndTests(unittest.TestCase):
    def test_build_generates_expected_files(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = root / "examples" / "yamada-anna.md"
        increments = root / "examples" / "increments"

        report = validate_inputs(source, increments)
        self.assertEqual(report["slug"], "yamada-anna")
        self.assertEqual(report["total_statements"], 4)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            wiki_root = build_wiki(source, output_root, increments)

            self.assertTrue((wiki_root / "index.md").exists())
            self.assertTrue((wiki_root / "timeline.md").exists())
            self.assertTrue((wiki_root / "topics" / "agents.md").exists())
            self.assertTrue((wiki_root / "_meta" / "statements.json").exists())

            index_text = (wiki_root / "index.md").read_text(encoding="utf-8")
            self.assertIn("Yamada Anna", index_text)
            self.assertIn("podcast-2026-04-10-evals-are-infra", (wiki_root / "sources.md").read_text(encoding="utf-8"))
            agents_text = (wiki_root / "topics" / "agents.md").read_text(encoding="utf-8")
            self.assertIn("Original Text", agents_text)

    def test_import_batch_generates_increment_that_build_can_use(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = root / "examples" / "yamada-anna.md"
        batch_input = root / "examples" / "raw" / "yamada-batch.md"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            generated_dir = tmp_root / "increments"
            output_increment = import_batch(batch_input, generated_dir)

            self.assertTrue(output_increment.exists())
            increment_text = output_increment.read_text(encoding="utf-8")
            self.assertIn("# Increment", increment_text)
            self.assertIn("Context engineering", increment_text)

            wiki_root = build_wiki(source, tmp_root / "dist", generated_dir)
            topic_text = (wiki_root / "topics" / "context-engineering.md").read_text(encoding="utf-8")
            self.assertIn("Context engineering is the delicate art and science", topic_text)

    def test_import_batch_accepts_loose_markdown_formats(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = root / "examples" / "yamada-anna.md"
        batch_input = root / "examples" / "raw" / "yamada-wild.md"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            generated_dir = tmp_root / "increments"
            output_increment = import_batch(
                batch_input,
                generated_dir,
                options=ImportOptions(person_slug="yamada-anna"),
            )

            increment_text = output_increment.read_text(encoding="utf-8")
            self.assertIn("## 2025-02-15-context-engineering", increment_text)
            self.assertIn("## unknown-tokens-are-the-new-software", increment_text)

            wiki_root = build_wiki(source, tmp_root / "dist", generated_dir)
            llms_text = (wiki_root / "topics" / "llms.md").read_text(encoding="utf-8")
            self.assertIn("Tokens are the new software.", llms_text)

    def test_ingest_single_statement_can_write_increment_and_build(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = root / "examples" / "yamada-anna.md"

        payload = load_payload_from_json(
            json.dumps(
                {
                    "person_slug": "yamada-anna",
                    "when": "2026-04-16T21:00:00+08:00",
                    "topics": ["agents", "evals"],
                    "source_refs": ["raw/live-feed.md#L120"],
                    "summary": "A live-ingested evals statement.",
                    "text": "If you cannot measure the behavior, you cannot improve the agent.",
                }
            )
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            result = ingest_statement(
                payload,
                tmp_root / "increments",
                source_path=source,
                build_output=tmp_root / "dist",
            )

            self.assertIn("increment_path", result)
            self.assertIn("wiki_root", result)
            increment_text = Path(result["increment_path"]).read_text(encoding="utf-8")
            self.assertIn("# Increment", increment_text)
            evals_text = Path(result["wiki_root"]).joinpath("topics", "evals.md").read_text(encoding="utf-8")
            self.assertIn("If you cannot measure the behavior", evals_text)

    def test_autotag_topics_can_write_tagged_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            source = tmp_root / "source.md"
            source.write_text(
                "\n".join(
                    [
                        "# Person",
                        "name: 测试人物",
                        "slug: test-person",
                        "aliases:",
                        "description: 测试。",
                        "",
                        "# Statements",
                        "",
                        "## s1",
                        "when: 2026-04-17",
                        "source_type: forum",
                        "text:",
                        "> AI 太火了，不如看看机器人和算力。",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            tagged_source = tmp_root / "tagged.md"
            report = autotag_source(source, tagged_source, replace_existing=True, max_topics=3)

            self.assertEqual(report["statement_count"], 1)
            tagged_text = tagged_source.read_text(encoding="utf-8")
            self.assertIn("topics: AI | 机器人 | 算力与芯片", tagged_text)
            wiki_root = build_wiki(tagged_source, tmp_root / "dist")
            self.assertTrue((wiki_root / "topics" / "ai.md").exists())
            self.assertTrue((wiki_root / "topics" / "机器人.md").exists())

    def test_wiki_backend_reads_built_wiki(self) -> None:
        root = Path(__file__).resolve().parent.parent
        source = root / "examples" / "yamada-anna.md"
        increments = root / "examples" / "increments"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            wiki_root = build_wiki(source, tmp_root / "dist", increments)
            backend = WikiBackend(tmp_root / "dist")

            people = backend.list_people()
            self.assertEqual(people[0]["slug"], "yamada-anna")
            self.assertIn("Yamada Anna", backend.get_index("yamada-anna"))
            topics = backend.list_topics("yamada-anna")
            self.assertTrue(any(item["topic"] == "agents" for item in topics))
            search = backend.search_statements("yamada-anna", query="measure", limit=5)
            self.assertGreaterEqual(search["total"], 1)
            statement = backend.get_statement("yamada-anna", "podcast-2026-04-10-evals-are-infra")
            self.assertIn("measure the behavior", statement["text"])


if __name__ == "__main__":
    unittest.main()
