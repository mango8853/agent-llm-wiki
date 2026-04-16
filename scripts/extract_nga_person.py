#!/usr/bin/env python3
import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


HEADER_RE = re.compile(r"^\*\*\[@(?P<name>.+?)\]\*\*发帖时间：(?P<when>\d{4}-\d{2}-\d{2} \d{2}:\d{2})$")
PID_RE = re.compile(r"^<!-- pid:(?P<pid>\d+)(?: uid:(?P<uid>-?\d+))?(?: page:(?P<page>\d+))? -->$")
REPLY_HEAD_RE = re.compile(r"^回复\[@(?P<target>.*?)\]\[(?P<time>.*?)\](?P<rest>.*)$")


@dataclass
class Statement:
    pid: str
    uid: Optional[str]
    page: Optional[str]
    alias: str
    when: str
    line_start: int
    line_end: int
    body_lines: List[str]
    reply_context: Optional[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract one NGA user's statements into llm-wiki format.")
    parser.add_argument("--input", action="append", required=True, help="Source posts.md path; may be repeated")
    parser.add_argument("--output", required=True, help="Destination person markdown path")
    parser.add_argument("--name", required=True, help="Person display name")
    parser.add_argument("--slug", required=True, help="Person slug")
    parser.add_argument("--aliases", required=True, help="Aliases separated by |")
    parser.add_argument("--description", default="", help="Optional person description")
    parser.add_argument(
        "--match-aliases",
        required=True,
        help="Header aliases to match, separated by |",
    )
    parser.add_argument(
        "--match-uids",
        default="",
        help="Optional uid list to match, separated by |",
    )
    return parser.parse_args()


def split_blocks(lines: List[str]) -> Iterable[tuple[int, int, List[str]]]:
    current: List[str] = []
    start = 1
    for lineno, line in enumerate(lines, start=1):
        if not current:
            start = lineno
        current.append(line)
        if line.strip() == "---":
            yield start, lineno, current
            current = []
    if current:
        yield start, len(lines), current


def normalize_when(when_text: str) -> str:
    return when_text.replace(" ", "T") + ":00+08:00"


def parse_statement(start: int, end: int, block: List[str]) -> Optional[Statement]:
    if len(block) < 3:
        return None

    pid = None
    uid = None
    page = None
    header_index = 0

    pid_match = PID_RE.match(block[0].strip())
    if pid_match:
        pid = pid_match.group("pid")
        uid = pid_match.group("uid")
        page = pid_match.group("page")
        header_index = 1

    if header_index >= len(block):
        return None

    header_match = HEADER_RE.match(block[header_index].strip())
    if not header_match:
        return None

    alias = header_match.group("name")
    when = normalize_when(header_match.group("when"))

    body = block[header_index + 1 :]
    if body and body[-1].strip() == "---":
        body = body[:-1]

    reply_context = None
    trimmed = [line.rstrip() for line in body]
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()

    if trimmed:
        reply_context, trimmed = extract_reply_context(trimmed)

    if not trimmed:
        return None

    return Statement(
        pid=pid or f"line-{start}",
        uid=uid,
        page=page,
        alias=alias,
        when=when,
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
    context: Optional[str]
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


def make_statement_id(statement: Statement) -> str:
    return f"nga-{statement.when[:10]}-{statement.pid}"


def statement_sort_key(statement: Statement) -> tuple[datetime, int, str]:
    return (
        datetime.fromisoformat(statement.when),
        int(statement.page or "0"),
        statement.pid,
    )


def title_from_body(lines: List[str]) -> str:
    joined = " ".join(line.strip() for line in lines if line.strip())
    joined = re.sub(r"\s+", " ", joined).strip()
    if len(joined) <= 28:
        return joined
    return joined[:28].rstrip() + "..."


def render_statement(statement: Statement, source_ref: str) -> str:
    parts = [
        f"## {make_statement_id(statement)}",
        f"when: {statement.when}",
        f"title: {title_from_body(statement.body_lines)}",
        "source_type: forum",
        f"source_link: {source_ref}",
        "source_refs:",
        f"- {source_ref}",
        "text:",
    ]
    for line in statement.body_lines:
        if line.strip():
            parts.append(f"> {line}")
        else:
            parts.append(">")
    if statement.reply_context:
        parts.append("notes:")
        parts.append(f"- {statement.reply_context}")
    return "\n".join(parts)


def main() -> int:
    args = parse_args()
    output_path = Path(args.output).resolve()
    input_paths = [Path(item).resolve() for item in args.input]

    match_aliases = {item.strip() for item in args.match_aliases.split("|") if item.strip()}
    match_uids = {item.strip() for item in args.match_uids.split("|") if item.strip()}

    statements: List[Statement] = []
    seen_pids: set[str] = set()
    source_map: dict[str, str] = {}
    for input_path in input_paths:
        lines = input_path.read_text(encoding="utf-8", errors="replace").splitlines()
        relative_source = os.path.relpath(input_path, output_path.parent.parent)
        for start, end, block in split_blocks(lines):
            statement = parse_statement(start, end, block)
            if statement is None:
                continue
            if statement.alias not in match_aliases and (not statement.uid or statement.uid not in match_uids):
                continue
            if statement.pid in seen_pids:
                continue
            seen_pids.add(statement.pid)
            statements.append(statement)
            source_map[statement.pid] = f"{relative_source}#L{statement.line_start}-L{statement.line_end}"

    statements.sort(key=statement_sort_key)

    output_parts = [
        "# Person",
        f"name: {args.name}",
        f"slug: {args.slug}",
        f"aliases: {args.aliases}",
    ]
    if args.description:
        output_parts.append(f"description: {args.description}")
    output_parts.extend(["", "# Statements", ""])

    for index, statement in enumerate(statements):
        source_ref = source_map[statement.pid]
        output_parts.append(render_statement(statement, source_ref))
        if index != len(statements) - 1:
            output_parts.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(output_parts) + "\n", encoding="utf-8")

    print(f"wrote {len(statements)} statements to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
