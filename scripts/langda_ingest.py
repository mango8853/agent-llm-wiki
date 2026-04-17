#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from llm_wiki.builder import build_wiki
from llm_wiki.ingest import StatementPayload, ingest_statement
from llm_wiki.paths import default_wiki_root
from llm_wiki.parser import FormatError, Person, Statement, parse_document
from llm_wiki.topic_autotag import infer_topics


DEFAULT_RAW_POSTS = Path("/home/mango/nga_spider/nga_downloads/自立自强，科学技术打头阵/posts.md")
DEFAULT_SOURCE_ROOT = Path("/home/mango/.llm-wiki/sources/langda")
DEFAULT_FEED_SOURCE = DEFAULT_SOURCE_ROOT / "langda_feed.md"
DEFAULT_BUILD_SOURCE = DEFAULT_SOURCE_ROOT / "langda.md"
DEFAULT_INCREMENTS_DIR = DEFAULT_SOURCE_ROOT / "increments"
HEADER_RE = re.compile(r"^\*\*\[@(?P<name>.+?)\]\*\*发帖时间：(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
PID_RE = re.compile(r"^<!-- pid:(?P<pid>\d+)(?: uid:(?P<uid>-?\d+))?(?: page:(?P<page>\d+))? -->$")
REPLY_HEAD_RE = re.compile(r"^回复\[@(?P<target>.*?)\]\[(?P<time>.*?)\](?P<rest>.*)$")


@dataclass
class NgaStatement:
    pid: str
    uid: Optional[str]
    alias: str
    when: str
    line_start: int
    line_end: int
    body_lines: List[str]
    reply_context: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Poll one NGA posts.md file, mirror new Langda statements into langda_feed.md, "
            "turn them into increments, and rebuild the wiki."
        )
    )
    parser.add_argument(
        "--raw-posts",
        type=Path,
        default=DEFAULT_RAW_POSTS,
        help="Source NGA posts.md file. Defaults to the known Langda crawler path.",
    )
    parser.add_argument(
        "--feed-source",
        type=Path,
        default=DEFAULT_FEED_SOURCE,
        help="Mirrored markdown feed of extracted Langda statements.",
    )
    parser.add_argument(
        "--build-source",
        type=Path,
        default=DEFAULT_BUILD_SOURCE,
        help="Stable base source markdown file used when rebuilding the wiki.",
    )
    parser.add_argument(
        "--increments-dir",
        type=Path,
        default=DEFAULT_INCREMENTS_DIR,
        help="Directory where generated increment markdown files will be stored.",
    )
    parser.add_argument(
        "--wiki-root",
        type=Path,
        default=default_wiki_root(),
        help="Wiki library root. Defaults to ~/.llm-wiki/wikis.",
    )
    parser.add_argument(
        "--match-aliases",
        default="狼大|-阿狼-",
        help="NGA aliases to treat as Langda statements, separated by |.",
    )
    parser.add_argument(
        "--match-uids",
        default="150058",
        help="Optional NGA uids to match, separated by |.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        help="Optional JSON file tracking already-ingested statement ids. Defaults inside increments-dir.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=600,
        help="Polling interval in seconds. Defaults to 600.",
    )
    parser.add_argument(
        "--bootstrap",
        choices=("skip-existing", "ingest-existing"),
        default="skip-existing",
        help="On first run, skip all existing feed statements or ingest them all. Defaults to skip-existing.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan only, then exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state_path = args.state_file or args.increments_dir / ".langda_ingest_state.json"
    args.feed_source.parent.mkdir(parents=True, exist_ok=True)
    args.increments_dir.mkdir(parents=True, exist_ok=True)
    args.wiki_root.mkdir(parents=True, exist_ok=True)
    match_aliases = _split_pipe_list(args.match_aliases)
    match_uids = _split_pipe_list(args.match_uids)

    while True:
        try:
            report = ingest_new_statements(
                raw_posts=args.raw_posts,
                feed_source=args.feed_source,
                build_source=args.build_source,
                increments_dir=args.increments_dir,
                wiki_root=args.wiki_root,
                state_path=state_path,
                bootstrap_mode=args.bootstrap,
                match_aliases=match_aliases,
                match_uids=match_uids,
            )
            print(json.dumps(report, ensure_ascii=False), flush=True)
        except Exception as exc:  # pragma: no cover - long-running script should keep polling
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
            if args.once:
                return 1

        if args.once:
            return 0
        time.sleep(max(args.poll_seconds, 1))


def ingest_new_statements(
    *,
    raw_posts: Path,
    feed_source: Path,
    build_source: Path,
    increments_dir: Path,
    wiki_root: Path,
    state_path: Path,
    bootstrap_mode: str,
    match_aliases: Sequence[str],
    match_uids: Sequence[str],
) -> dict:
    build_doc = parse_document(build_source)
    if build_doc.kind != "source" or build_doc.person is None:
        raise FormatError(f"{build_source}: build source must contain # Person")

    feed_sync = sync_feed_from_raw_posts(
        raw_posts=raw_posts,
        feed_source=feed_source,
        person=build_doc.person,
        match_aliases=match_aliases,
        match_uids=match_uids,
    )
    feed_doc = parse_document(feed_source)
    if feed_doc.kind != "source":
        raise FormatError(f"{feed_source}: feed source must use # Person + # Statements")

    state = load_state(state_path)
    known_ids = set(state.get("seen_statement_ids", []))

    if not state.get("initialized"):
        if bootstrap_mode == "skip-existing":
            known_ids.update(statement.id for statement in feed_doc.statements)
        state.update(
            {
                "initialized": True,
                "person_slug": build_doc.person.slug,
                "seen_statement_ids": sorted(known_ids),
                "last_scan_at": _timestamp(),
            }
        )
        save_state(state_path, state)
        return {
            "ok": True,
            "bootstrap": bootstrap_mode,
            "new_statements": 0,
            "rebuilt": False,
            "wiki_root": str(wiki_root / build_doc.person.slug),
            "feed_updates": feed_sync,
        }

    new_statements = [statement for statement in feed_doc.statements if statement.id not in known_ids]
    if not new_statements:
        state["last_scan_at"] = _timestamp()
        save_state(state_path, state)
        return {
            "ok": True,
            "bootstrap": None,
            "new_statements": 0,
            "rebuilt": False,
            "wiki_root": str(wiki_root / build_doc.person.slug),
            "feed_updates": feed_sync,
        }

    written_increment_paths: List[str] = []
    for statement in new_statements:
        payload = statement_to_payload(build_doc.person.slug, statement)
        result = ingest_statement(
            payload,
            increments_dir,
            source_path=None,
            build_output=None,
        )
        written_increment_paths.append(result["increment_path"])
        known_ids.add(statement.id)

    rebuilt_path = build_wiki(build_source, wiki_root, increments_dir)
    state.update(
        {
            "initialized": True,
            "person_slug": build_doc.person.slug,
            "seen_statement_ids": sorted(known_ids),
            "last_scan_at": _timestamp(),
            "last_rebuild_at": _timestamp(),
        }
    )
    save_state(state_path, state)
    return {
        "ok": True,
        "bootstrap": None,
        "new_statements": len(new_statements),
        "rebuilt": True,
        "wiki_root": str(rebuilt_path),
        "increment_paths": written_increment_paths,
        "statement_ids": [statement.id for statement in new_statements],
        "feed_updates": feed_sync,
    }


def sync_feed_from_raw_posts(
    *,
    raw_posts: Path,
    feed_source: Path,
    person: Person,
    match_aliases: Sequence[str],
    match_uids: Sequence[str],
) -> dict:
    if not raw_posts.exists():
        if feed_source.exists():
            return {"raw_posts_found": False, "appended_to_feed": 0}
        raise FileNotFoundError(f"raw posts file not found: {raw_posts}")

    extracted = extract_matching_nga_statements(raw_posts, match_aliases=match_aliases, match_uids=match_uids)
    existing_ids = set()
    if feed_source.exists():
        existing_doc = parse_document(feed_source)
        existing_ids = {statement.id for statement in existing_doc.statements}

    new_statements = [statement for statement in extracted if statement.id not in existing_ids]
    if new_statements:
        append_feed_statements(feed_source, person, new_statements)
    elif not feed_source.exists():
        append_feed_statements(feed_source, person, [])

    return {
        "raw_posts_found": True,
        "extracted_total": len(extracted),
        "appended_to_feed": len(new_statements),
        "feed_source": str(feed_source),
    }


def statement_to_payload(person_slug: str, statement: Statement) -> StatementPayload:
    return StatementPayload(
        person_slug=person_slug,
        id=statement.id,
        when=statement.when,
        sort_date=statement.sort_date,
        title=statement.title,
        text=statement.text,
        summary=statement.summary,
        source_type=statement.source_type,
        source_link=statement.source_link,
        source_refs=list(statement.source_refs),
        topics=list(statement.topics),
        tags=list(statement.tags),
        stance=statement.stance,
        claims=list(statement.claims),
        notes=list(statement.notes),
        canonical=statement.canonical,
        update_note=f"Ingested from feed file at {_timestamp()}",
    )


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _timestamp() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def extract_matching_nga_statements(
    raw_posts: Path,
    *,
    match_aliases: Sequence[str],
    match_uids: Sequence[str],
) -> List[Statement]:
    alias_set = {item.strip() for item in match_aliases if item.strip()}
    uid_set = {item.strip() for item in match_uids if item.strip()}
    lines = raw_posts.read_text(encoding="utf-8", errors="replace").splitlines()

    statements: List[Statement] = []
    seen_ids: set[str] = set()
    for start, end, block in split_nga_blocks(lines):
        parsed = parse_nga_statement(start, end, block)
        if parsed is None:
            continue
        if parsed.alias not in alias_set and (not parsed.uid or parsed.uid not in uid_set):
            continue
        statement_id = f"nga-{parsed.when[:10]}-{parsed.pid}"
        if statement_id in seen_ids:
            continue
        seen_ids.add(statement_id)
        source_ref = f"{raw_posts}#L{parsed.line_start}-L{parsed.line_end}"
        text = "\n".join(parsed.body_lines)
        provisional = Statement(
            id=statement_id,
            when=parsed.when,
            sort_date=parsed.when,
            title=title_from_body(parsed.body_lines),
            text=text,
            source_type="forum",
            source_link=source_ref,
            source_refs=[source_ref],
            notes=[parsed.reply_context] if parsed.reply_context else [],
            from_file=str(raw_posts),
        )
        topics = infer_topics(provisional, max_topics=4)
        statements.append(
            Statement(
                id=provisional.id,
                when=provisional.when,
                text=provisional.text,
                sort_date=provisional.sort_date,
                source_type=provisional.source_type,
                title=provisional.title,
                source_link=provisional.source_link,
                source_refs=provisional.source_refs,
                topics=topics,
                notes=provisional.notes,
                from_file=provisional.from_file,
            )
        )
    return statements


def append_feed_statements(feed_source: Path, person: Person, statements: Sequence[Statement]) -> None:
    feed_source.parent.mkdir(parents=True, exist_ok=True)
    if not feed_source.exists():
        header = [
            "# Person",
            f"name: {person.name}",
            f"slug: {person.slug}",
            f"aliases: {' | '.join(person.aliases)}" if person.aliases else "aliases:",
            f"description: {person.description}" if person.description else "description:",
            "",
            "# Statements",
            "",
        ]
        feed_source.write_text("\n".join(header), encoding="utf-8")
    if not statements:
        return

    chunks = [render_feed_statement(statement) for statement in statements]
    existing = feed_source.read_text(encoding="utf-8")
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    with feed_source.open("a", encoding="utf-8") as handle:
        handle.write(separator)
        handle.write("\n\n".join(chunks))
        handle.write("\n")


def render_feed_statement(statement: Statement) -> str:
    lines = [f"## {statement.id}", f"when: {statement.when}"]
    if statement.sort_date:
        lines.append(f"sort_date: {statement.sort_date}")
    if statement.title:
        lines.append(f"title: {statement.title}")
    if statement.source_type:
        lines.append(f"source_type: {statement.source_type}")
    if statement.source_link:
        lines.append(f"source_link: {statement.source_link}")
    if statement.source_refs:
        lines.append("source_refs:")
        for ref in statement.source_refs:
            lines.append(f"- {ref}")
    if statement.topics:
        lines.append(f"topics: {' | '.join(statement.topics)}")
    if statement.notes:
        lines.append("notes:")
        for note in statement.notes:
            lines.append(f"- {note}")
    lines.append("text:")
    for text_line in statement.text.splitlines():
        lines.append(f"> {text_line}" if text_line else ">")
    return "\n".join(lines)


def split_nga_blocks(lines: List[str]) -> List[tuple[int, int, List[str]]]:
    blocks: List[tuple[int, int, List[str]]] = []
    current: List[str] = []
    start = 1
    for lineno, line in enumerate(lines, start=1):
        if not current:
            start = lineno
        current.append(line)
        if line.strip() == "---":
            blocks.append((start, lineno, current))
            current = []
    if current:
        blocks.append((start, len(lines), current))
    return blocks


def parse_nga_statement(start: int, end: int, block: List[str]) -> Optional[NgaStatement]:
    if len(block) < 3:
        return None

    pid = None
    uid = None
    header_index = 0
    pid_match = PID_RE.match(block[0].strip())
    if pid_match:
        pid = pid_match.group("pid")
        uid = pid_match.group("uid")
        header_index = 1
    if header_index >= len(block):
        return None

    header_match = HEADER_RE.match(block[header_index].strip())
    if not header_match:
        return None

    body = block[header_index + 1 :]
    if body and body[-1].strip() == "---":
        body = body[:-1]
    trimmed = [line.rstrip() for line in body]
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    if not trimmed:
        return None

    reply_context, trimmed = extract_reply_context(trimmed)
    if not trimmed:
        return None

    return NgaStatement(
        pid=pid or f"line-{start}",
        uid=uid,
        alias=header_match.group("name"),
        when=normalize_when(header_match.group("when")),
        line_start=start,
        line_end=end,
        body_lines=trimmed,
        reply_context=reply_context,
    )


def extract_reply_context(lines: List[str]) -> tuple[Optional[str], List[str]]:
    first = lines[0].strip()
    match = REPLY_HEAD_RE.match(first)
    if not match:
        return None, lines

    target = match.group("target")
    reply_time = match.group("time")
    rest = match.group("rest").strip()
    consumed = 1
    if "<<<" not in rest:
        context = f"回复语境：回复 {target} 在 {reply_time} 的发言"
    else:
        quote_parts = [rest.split("<<<", 1)[1]]
        while ">>>" not in quote_parts[-1] and consumed < len(lines):
            quote_parts.append(lines[consumed].strip())
            consumed += 1
        joined = "\n".join(quote_parts)
        quoted = joined.split(">>>", 1)[0]
        quoted = re.sub(r"\s+", " ", quoted).strip()
        context = f"回复语境：{target} 在 {reply_time} 说“{quoted}”" if quoted else None

    remaining = lines[consumed:]
    while remaining and not remaining[0].strip():
        remaining.pop(0)
    return context, remaining


def normalize_when(when_text: str) -> str:
    return when_text.replace(" ", "T") + ":00+08:00"


def title_from_body(lines: Sequence[str]) -> str:
    joined = " ".join(line.strip() for line in lines if line.strip())
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined if len(joined) <= 28 else joined[:28].rstrip() + "..."


def _split_pipe_list(raw: str) -> List[str]:
    return [item.strip() for item in raw.split("|") if item.strip()]


if __name__ == "__main__":
    raise SystemExit(main())
