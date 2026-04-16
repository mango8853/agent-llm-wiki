from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
from typing import Dict, List, Optional


LIST_FIELDS = {"aliases", "topics", "tags"}
BLOCK_LIST_FIELDS = {"claims", "notes", "source_refs"}
BLOCK_TEXT_FIELDS = {"excerpt", "text"}
BOOL_FIELDS = {"canonical"}


class FormatError(ValueError):
    """Raised when a markdown source file does not match the expected schema."""


@dataclass
class Statement:
    id: str
    when: str
    text: str
    sort_date: Optional[str] = None
    source_type: Optional[str] = None
    title: Optional[str] = None
    source_link: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    summary: Optional[str] = None
    topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    stance: Optional[str] = None
    claims: List[str] = field(default_factory=list)
    excerpt: str = ""
    notes: List[str] = field(default_factory=list)
    canonical: bool = False
    from_file: str = ""


@dataclass
class Person:
    name: str
    slug: str
    aliases: List[str] = field(default_factory=list)
    description: str = ""


@dataclass
class Document:
    kind: str
    path: Path
    person: Optional[Person]
    person_slug: Optional[str]
    update_note: Optional[str]
    statements: List[Statement]


def slugify(value: str) -> str:
    cleaned = re.sub(r"[^\w]+", "-", value.strip().lower(), flags=re.UNICODE)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "item"


def parse_document(path: Path) -> Document:
    lines = path.read_text(encoding="utf-8").splitlines()
    top_section = None
    person_data: Dict[str, object] = {}
    increment_data: Dict[str, object] = {}
    statements: List[Statement] = []
    current_statement: Optional[Dict[str, object]] = None
    current_block: Optional[str] = None

    def finish_statement() -> None:
        nonlocal current_statement
        if current_statement is None:
            return
        statements.append(build_statement(current_statement, path))
        current_statement = None

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip()
        if line.startswith("# "):
            finish_statement()
            current_block = None
            title = line[2:].strip().lower()
            if title == "person":
                top_section = "person"
            elif title == "increment":
                top_section = "increment"
            elif title == "statements":
                top_section = "statements"
            else:
                raise FormatError(f"{path}:{lineno}: unsupported top-level section '{line[2:].strip()}'")
            continue

        if top_section == "statements" and line.startswith("## "):
            finish_statement()
            current_statement = {"id": line[3:].strip()}
            current_block = None
            continue

        if not line.strip():
            continue

        if top_section == "person":
            current_block = _parse_metadata_line(person_data, current_block, line, path, lineno)
        elif top_section == "increment":
            current_block = _parse_metadata_line(increment_data, current_block, line, path, lineno)
        elif top_section == "statements":
            if current_statement is None:
                raise FormatError(f"{path}:{lineno}: statement content must be under a '## <id>' heading")
            current_block = _parse_metadata_line(current_statement, current_block, line, path, lineno)
        else:
            raise FormatError(f"{path}:{lineno}: content must be under # Person, # Increment, or # Statements")

    finish_statement()

    if person_data and increment_data:
        raise FormatError(f"{path}: file cannot contain both # Person and # Increment")
    if not person_data and not increment_data:
        raise FormatError(f"{path}: file must contain either # Person or # Increment")
    if not statements:
        raise FormatError(f"{path}: file must contain at least one statement")

    if person_data:
        name = _required_str(person_data, "name", path)
        slug = str(person_data.get("slug") or slugify(name))
        person = Person(
            name=name,
            slug=slug,
            aliases=_coerce_list(person_data.get("aliases")),
            description=str(person_data.get("description", "")).strip(),
        )
        return Document(
            kind="source",
            path=path,
            person=person,
            person_slug=person.slug,
            update_note=None,
            statements=statements,
        )

    person_slug = _required_str(increment_data, "person_slug", path)
    update_note = str(increment_data.get("update_note", "")).strip() or None
    return Document(
        kind="increment",
        path=path,
        person=None,
        person_slug=person_slug,
        update_note=update_note,
        statements=statements,
    )


def build_statement(data: Dict[str, object], path: Path) -> Statement:
    statement_id = _required_str(data, "id", path)
    when = _optional_str(data.get("when")) or _optional_str(data.get("date")) or "unknown"
    sort_date = _optional_str(data.get("sort_date")) or _infer_sort_date(when)
    if sort_date:
        _validate_sort_date(sort_date, path, statement_id)

    text = _optional_str(data.get("text")) or _optional_str(data.get("excerpt"))
    if not text:
        raise FormatError(f"{path}: statement '{statement_id}' must include 'text' or 'excerpt'")

    source_link = _optional_str(data.get("source_link"))
    source_refs = _coerce_list(data.get("source_refs"))
    if source_link and source_link not in source_refs:
        source_refs.append(source_link)

    return Statement(
        id=statement_id,
        when=when,
        text=text,
        sort_date=sort_date,
        source_type=_optional_str(data.get("source_type")),
        title=_optional_str(data.get("title")),
        source_link=source_link,
        source_refs=source_refs,
        summary=_optional_str(data.get("summary")),
        topics=_coerce_list(data.get("topics")),
        tags=_coerce_list(data.get("tags")),
        stance=_optional_str(data.get("stance")),
        claims=_coerce_list(data.get("claims")),
        excerpt=_optional_str(data.get("excerpt")) or text,
        notes=_coerce_list(data.get("notes")),
        canonical=bool(data.get("canonical", False)),
        from_file=str(path),
    )


def _parse_metadata_line(
    target: Dict[str, object],
    current_block: Optional[str],
    line: str,
    path: Path,
    lineno: int,
) -> Optional[str]:
    key_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*))?$", line)
    if key_match:
        key = key_match.group(1)
        value = (key_match.group(2) or "").strip()
        if not value:
            if key in BLOCK_LIST_FIELDS:
                target[key] = []
            elif key in BLOCK_TEXT_FIELDS:
                target[key] = ""
            else:
                target[key] = ""
            return key

        if key in LIST_FIELDS:
            target[key] = [item.strip() for item in value.split("|") if item.strip()]
        elif key in BOOL_FIELDS:
            target[key] = value.lower() in {"1", "true", "yes"}
        else:
            target[key] = value
        return None

    if current_block in BLOCK_LIST_FIELDS and line.startswith("- "):
        items = target.setdefault(current_block, [])
        if not isinstance(items, list):
            raise FormatError(f"{path}:{lineno}: field '{current_block}' must be a list")
        items.append(line[2:].strip())
        return current_block

    if current_block in BLOCK_LIST_FIELDS and line.startswith("  "):
        items = target.get(current_block)
        if not items:
            raise FormatError(f"{path}:{lineno}: continuation line without a list item")
        items[-1] = f"{items[-1]} {line.strip()}"
        return current_block

    if current_block in BLOCK_TEXT_FIELDS and line.startswith(">"):
        current_value = str(target.get(current_block, "")).strip()
        excerpt_line = line[1:].strip()
        target[current_block] = f"{current_value}\n{excerpt_line}".strip()
        return current_block

    if current_block in BLOCK_TEXT_FIELDS and line.startswith("  "):
        current_value = str(target.get(current_block, "")).strip()
        target[current_block] = f"{current_value}\n{line.strip()}".strip()
        return current_block

    raise FormatError(f"{path}:{lineno}: could not parse line '{line}'")


def _required_str(data: Dict[str, object], key: str, path: Path, statement_id: Optional[str] = None) -> str:
    value = _optional_str(data.get(key))
    if value:
        return value
    if statement_id:
        raise FormatError(f"{path}: statement '{statement_id}' is missing required field '{key}'")
    raise FormatError(f"{path}: missing required field '{key}'")


def _optional_str(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _validate_sort_date(date_value: str, path: Path, statement_id: str) -> None:
    normalized = date_value.replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}", normalized):
        return
    if re.fullmatch(r"\d{4}-\d{2}", normalized):
        return
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        return
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise FormatError(
            f"{path}: statement '{statement_id}' has an invalid sort_date '{date_value}'"
        ) from exc


def _infer_sort_date(when: str) -> Optional[str]:
    normalized = when.strip()
    if not normalized or normalized.lower() == "unknown":
        return None
    if re.fullmatch(r"\d{4}", normalized):
        return normalized
    if re.fullmatch(r"\d{4}-\d{2}", normalized):
        return normalized
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", normalized):
        return normalized
    candidate = normalized.replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return None
    return normalized


def topic_slug(topic: str) -> str:
    return slugify(topic)


def sort_statements(statements: List[Statement]) -> List[Statement]:
    return sorted(
        statements,
        key=lambda item: (_sort_bucket(item.sort_date), _sort_value(item.sort_date), item.id),
        reverse=True,
    )


def group_by_topic(statements: List[Statement]) -> Dict[str, List[Statement]]:
    grouped: Dict[str, List[Statement]] = {}
    for statement in statements:
        for topic in statement.topics or ["uncategorized"]:
            grouped.setdefault(topic, []).append(statement)
    return {topic: sort_statements(items) for topic, items in sorted(grouped.items(), key=lambda pair: pair[0].lower())}


def statement_label(statement: Statement) -> str:
    title = statement.title or statement.summary or _shorten(statement.text)
    return title.strip()


def _sort_bucket(sort_date: Optional[str]) -> int:
    return 1 if sort_date else 0


def _sort_value(sort_date: Optional[str]) -> str:
    if not sort_date:
        return ""
    if re.fullmatch(r"\d{4}", sort_date):
        return f"{sort_date}-00-00T00:00:00"
    if re.fullmatch(r"\d{4}-\d{2}", sort_date):
        return f"{sort_date}-00T00:00:00"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", sort_date):
        return f"{sort_date}T00:00:00"
    return sort_date.replace("Z", "+00:00")


def _shorten(text: str, limit: int = 72) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."
