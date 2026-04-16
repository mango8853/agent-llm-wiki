from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .builder import build_wiki, validate_inputs
from .ingest import ingest_statement, load_payload_from_json
from .importer import ImportOptions, import_batch
from .parser import FormatError, slugify
from .topic_autotag import autotag_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="llm-wiki", description="Build a person-centric markdown wiki.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_cmd = subparsers.add_parser("build", help="Build a wiki from a source markdown file.")
    build_cmd.add_argument("--source", required=True, type=Path, help="Base markdown file with # Person and # Statements.")
    build_cmd.add_argument("--increments", type=Path, help="Directory with increment markdown files.")
    build_cmd.add_argument("--output", required=True, type=Path, help="Directory where the wiki will be generated.")

    check_cmd = subparsers.add_parser("check", help="Validate source markdown files.")
    check_cmd.add_argument("--source", required=True, type=Path, help="Base markdown file with # Person and # Statements.")
    check_cmd.add_argument("--increments", type=Path, help="Directory with increment markdown files.")

    autotag_cmd = subparsers.add_parser("autotag-topics", help="Infer topics for statements in a source markdown file.")
    autotag_cmd.add_argument("--source", required=True, type=Path, help="Source markdown file with # Person and # Statements.")
    autotag_cmd.add_argument("--output", type=Path, help="Optional output file. Defaults to overwriting --source.")
    autotag_cmd.add_argument("--replace-existing", action="store_true", help="Replace topics that are already present.")
    autotag_cmd.add_argument("--max-topics", type=int, default=4, help="Maximum number of inferred topics per statement.")

    ingest_cmd = subparsers.add_parser("ingest-statement", help="Ingest one statement from a JSON payload.")
    ingest_cmd.add_argument("--increments", required=True, type=Path, help="Directory where single-statement increments will be written.")
    ingest_cmd.add_argument("--input-json", type=Path, help="JSON payload file. If omitted, JSON is read from stdin.")
    ingest_cmd.add_argument("--person-slug", help="Override or provide person_slug for the payload.")
    ingest_cmd.add_argument("--source", type=Path, help="Optional base source file to rebuild the wiki immediately.")
    ingest_cmd.add_argument("--build-output", type=Path, help="Optional wiki output directory. Requires --source.")

    import_cmd = subparsers.add_parser("import-batch", help="Convert a long batch markdown file into a standard increment file.")
    import_cmd.add_argument("--input", required=True, type=Path, help="Batch markdown file with # Batch and # Entries.")
    import_cmd.add_argument("--output", required=True, type=Path, help="Output increment markdown file or directory.")
    import_cmd.add_argument("--person-slug", help="Override or provide the target person slug for loose markdown files.")
    import_cmd.add_argument("--update-note", help="Optional update note to include in the generated increment.")
    import_cmd.add_argument("--default-when", help="Default when value for imported entries.")
    import_cmd.add_argument("--default-sort-date", help="Default sort_date value for imported entries.")
    import_cmd.add_argument("--default-source-type", help="Default source_type for imported entries.")
    import_cmd.add_argument("--default-source-link", help="Default source_link for imported entries.")
    import_cmd.add_argument("--default-topic", action="append", default=[], help="Default topic to apply. Repeatable.")
    import_cmd.add_argument("--default-tag", action="append", default=[], help="Default tag to apply. Repeatable.")
    import_cmd.add_argument("--default-source-ref", action="append", default=[], help="Default source ref to apply. Repeatable.")

    init_cmd = subparsers.add_parser("init", help="Create starter templates for a new person wiki.")
    init_cmd.add_argument("--name", required=True, help="Person name.")
    init_cmd.add_argument("--output", required=True, type=Path, help="Directory where templates will be written.")
    init_cmd.add_argument("--slug", help="Optional custom slug.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            wiki_root = build_wiki(args.source, args.output, args.increments)
            print(str(wiki_root))
            return 0

        if args.command == "check":
            report = validate_inputs(args.source, args.increments)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.command == "autotag-topics":
            report = autotag_source(
                args.source,
                args.output,
                replace_existing=args.replace_existing,
                max_topics=args.max_topics,
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        if args.command == "ingest-statement":
            raw_json = args.input_json.read_text(encoding="utf-8") if args.input_json else sys.stdin.read()
            payload = load_payload_from_json(raw_json, person_slug_override=args.person_slug)
            result = ingest_statement(
                payload,
                args.increments,
                source_path=args.source,
                build_output=args.build_output,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0

        if args.command == "import-batch":
            options = ImportOptions(
                person_slug=args.person_slug,
                update_note=args.update_note,
                default_when=args.default_when,
                default_sort_date=args.default_sort_date,
                default_source_type=args.default_source_type,
                default_source_link=args.default_source_link,
                default_topics=args.default_topic,
                default_tags=args.default_tag,
                default_source_refs=args.default_source_ref,
            )
            output_path = import_batch(args.input, args.output, options=options)
            print(str(output_path))
            return 0

        if args.command == "init":
            slug = args.slug or slugify(args.name)
            write_templates(args.output, args.name, slug)
            print(str(args.output))
            return 0

        parser.error("unsupported command")
        return 2
    except FormatError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def write_templates(output_dir: Path, name: str, slug: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    increments_dir = output_dir / "increments"
    increments_dir.mkdir(parents=True, exist_ok=True)

    source_template = f"""# Person
name: {name}
slug: {slug}
aliases:
description: Add a short person description here.

# Statements

## example-{slug}-statement
when: 2026-01-01T09:30:00+08:00
sort_date: 2026-01-01T09:30:00+08:00
title: Optional short label for this statement
source_refs:
- raw/transcript-001.md#L10
- https://example.com/source
topics: topic-one | topic-two
summary: Optional one-line summary of this statement.
text:
> Replace with the original statement text.
claims:
- Replace with one claim.
notes:
- Replace with an annotation about why this statement matters.
canonical: true
"""

    increment_template = f"""# Increment
person_slug: {slug}
update_note: Describe what was added in this increment.

# Statements

## example-increment-statement
when: unknown
sort_date:
source_refs:
- raw/new-batch.md#L50
topics: topic-one
summary: Optional one-line summary for the incremental statement.
text:
> Replace with the new original statement text.
claims:
- Replace with one claim.
"""

    (output_dir / f"{slug}.md").write_text(source_template, encoding="utf-8")
    (increments_dir / "2026-01-02-example.md").write_text(increment_template, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
