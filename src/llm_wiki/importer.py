from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import re
from typing import Dict, List, Optional

from .parser import FormatError, slugify


BATCH_LIST_FIELDS = {"default_topics", "default_tags", "default_source_refs", "topics", "tags", "source_refs"}
TOP_LEVEL_BATCH_KEYS = {
    "person_slug",
    "update_note",
    "default_when",
    "default_sort_date",
    "default_source_type",
    "default_source_link",
    "default_topics",
    "default_tags",
    "default_source_refs",
}


@dataclass
class BatchEntry:
    heading: str
    id: Optional[str] = None
    when: Optional[str] = None
    sort_date: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    source_type: Optional[str] = None
    source_link: Optional[str] = None
    source_refs: List[str] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    stance: Optional[str] = None
    canonical: Optional[bool] = None
    text: str = ""


@dataclass
class BatchDocument:
    path: Path
    person_slug: str
    update_note: Optional[str]
    default_when: Optional[str]
    default_sort_date: Optional[str]
    default_source_type: Optional[str]
    default_source_link: Optional[str]
    default_topics: List[str]
    default_tags: List[str]
    default_source_refs: List[str]
    entries: List[BatchEntry]


@dataclass
class ImportOptions:
    person_slug: Optional[str] = None
    update_note: Optional[str] = None
    default_when: Optional[str] = None
    default_sort_date: Optional[str] = None
    default_source_type: Optional[str] = None
    default_source_link: Optional[str] = None
    default_topics: List[str] = field(default_factory=list)
    default_tags: List[str] = field(default_factory=list)
    default_source_refs: List[str] = field(default_factory=list)


def import_batch(batch_path: Path, output_path: Path, options: Optional[ImportOptions] = None) -> Path:
    batch = parse_batch_file(batch_path, options=options)
    final_output = _resolve_output_path(output_path, batch.person_slug)
    final_output.parent.mkdir(parents=True, exist_ok=True)
    final_output.write_text(render_increment(batch), encoding="utf-8")
    return final_output


def parse_batch_file(path: Path, options: Optional[ImportOptions] = None) -> BatchDocument:
    lines = path.read_text(encoding="utf-8").splitlines()
    options = options or ImportOptions()
    if any(line.strip().lower() == "# batch" for line in lines):
        batch = _parse_structured_batch_file(path, lines)
    else:
        batch = _parse_loose_batch_file(path, lines)
    return _apply_import_options(batch, options)


def _parse_structured_batch_file(path: Path, lines: List[str]) -> BatchDocument:
    top_section = None
    batch_meta: Dict[str, object] = {}
    entries: List[BatchEntry] = []
    current_entry: Optional[Dict[str, object]] = None
    entry_body: List[str] = []
    body_started = False
    batch_list_key: Optional[str] = None
    entry_list_key: Optional[str] = None

    def finish_entry() -> None:
        nonlocal current_entry, entry_body, body_started, entry_list_key
        if current_entry is None:
            return
        body_text = _normalize_body(entry_body)
        if not body_text:
            raise FormatError(f"{path}: entry '{current_entry.get('heading', 'unknown')}' must include body text")
        current_entry["text"] = body_text
        entries.append(_build_entry(current_entry, path))
        current_entry = None
        entry_body = []
        body_started = False
        entry_list_key = None

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        if line.startswith("# "):
            finish_entry()
            title = line[2:].strip().lower()
            if title == "batch":
                top_section = "batch"
            elif title == "entries":
                top_section = "entries"
            else:
                raise FormatError(f"{path}:{lineno}: unsupported top-level section '{line[2:].strip()}'")
            continue

        if top_section == "entries" and line.startswith("## "):
            finish_entry()
            current_entry = {"heading": line[3:].strip()}
            continue

        if top_section is None:
            if not line.strip():
                continue
            raise FormatError(f"{path}:{lineno}: content must be under # Batch or # Entries")

        if top_section == "batch":
            if not line.strip():
                batch_list_key = None
                continue
            batch_list_key = _parse_metadata(batch_meta, line, path, lineno, batch_list_key)
            continue

        if current_entry is None:
            if not line.strip():
                continue
            raise FormatError(f"{path}:{lineno}: entry content must be under a '## <heading>' section")

        if not body_started and (_looks_like_metadata(line) or (entry_list_key and line.startswith("- "))):
            entry_list_key = _parse_metadata(current_entry, line, path, lineno, entry_list_key)
        else:
            body_started = body_started or bool(line.strip())
            if body_started:
                entry_list_key = None
            entry_body.append(line)

    finish_entry()

    if not entries:
        raise FormatError(f"{path}: batch file must contain at least one entry under # Entries")

    person_slug = _required_value(batch_meta, "person_slug", path)
    return BatchDocument(
        path=path,
        person_slug=person_slug,
        update_note=_optional_text(batch_meta.get("update_note")),
        default_when=_optional_text(batch_meta.get("default_when")),
        default_sort_date=_optional_text(batch_meta.get("default_sort_date")),
        default_source_type=_optional_text(batch_meta.get("default_source_type")),
        default_source_link=_optional_text(batch_meta.get("default_source_link")),
        default_topics=_coerce_list(batch_meta.get("default_topics")),
        default_tags=_coerce_list(batch_meta.get("default_tags")),
        default_source_refs=_coerce_list(batch_meta.get("default_source_refs")),
        entries=entries,
    )


def _parse_loose_batch_file(path: Path, lines: List[str]) -> BatchDocument:
    batch_meta: Dict[str, object] = {}
    entries: List[BatchEntry] = []
    current_entry: Optional[Dict[str, object]] = None
    current_list_key: Optional[str] = None
    body_started = False
    saw_entry = False

    def finish_entry() -> None:
        nonlocal current_entry, current_list_key, body_started, saw_entry
        if current_entry is None:
            return
        text = _normalize_body(_coerce_list(current_entry.pop("__body__", [])))
        if text:
            if current_entry.get("heading") in {None, "", "Untitled statement"}:
                first_line = next((line for line in text.splitlines() if line.strip()), "Untitled statement")
                current_entry["heading"] = _infer_heading_from_line(first_line)
            current_entry["text"] = text
            entries.append(_build_entry(current_entry, path))
            saw_entry = True
        current_entry = None
        current_list_key = None
        body_started = False

    def ensure_entry(heading: Optional[str] = None) -> Dict[str, object]:
        nonlocal current_entry
        if current_entry is None:
            current_entry = {"heading": heading or "Untitled statement", "__body__": []}
        elif heading and (current_entry.get("heading") in {None, "", "Untitled statement"}):
            current_entry["heading"] = heading
        return current_entry

    for lineno, raw_line in enumerate(lines, start=1):
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if not stripped:
            current_list_key = None
            if current_entry is not None:
                current_entry.setdefault("__body__", []).append("")
            continue

        if _is_horizontal_rule(stripped):
            finish_entry()
            continue

        heading_match = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading_match:
            finish_entry()
            current_entry = {"heading": heading_match.group(2).strip(), "__body__": []}
            current_list_key = None
            body_started = False
            continue

        if not saw_entry and current_entry is None and (_looks_like_metadata(line) or (current_list_key and line.startswith("- "))):
            if line.startswith("- ") and current_list_key:
                current_list_key = _parse_metadata(batch_meta, line, path, lineno, current_list_key)
                continue
            key = line.split(":", 1)[0].strip()
            if key in TOP_LEVEL_BATCH_KEYS or key in BATCH_LIST_FIELDS:
                current_list_key = _parse_metadata(batch_meta, line, path, lineno, current_list_key)
                continue

        if current_entry is None and _looks_like_metadata(line):
            key = line.split(":", 1)[0].strip()
            if key in {"when", "sort_date", "id", "title", "summary", "source_type", "source_link", "source_refs", "topics", "tags", "stance", "canonical"}:
                current_entry = {"heading": "Untitled statement", "__body__": []}

        if current_entry is not None and not body_started and (_looks_like_metadata(line) or (current_list_key and line.startswith("- "))):
            current_list_key = _parse_metadata(current_entry, line, path, lineno, current_list_key)
            continue

        if current_entry is None:
            inferred_heading = _infer_heading_from_line(line)
            current_entry = {"heading": inferred_heading, "__body__": []}

        current_entry.setdefault("__body__", []).append(line)
        body_started = body_started or bool(stripped)
        current_list_key = None

    finish_entry()

    if not entries:
        raise FormatError(f"{path}: could not infer any statements from the markdown file")

    person_slug = _optional_text(batch_meta.get("person_slug")) or "unknown-person"
    return BatchDocument(
        path=path,
        person_slug=person_slug,
        update_note=_optional_text(batch_meta.get("update_note")),
        default_when=_optional_text(batch_meta.get("default_when")),
        default_sort_date=_optional_text(batch_meta.get("default_sort_date")),
        default_source_type=_optional_text(batch_meta.get("default_source_type")),
        default_source_link=_optional_text(batch_meta.get("default_source_link")),
        default_topics=_coerce_list(batch_meta.get("default_topics")),
        default_tags=_coerce_list(batch_meta.get("default_tags")),
        default_source_refs=_coerce_list(batch_meta.get("default_source_refs")) or [str(path)],
        entries=entries,
    )


def render_increment(batch: BatchDocument) -> str:
    lines = [
        "# Increment",
        f"person_slug: {batch.person_slug}",
    ]
    if batch.update_note:
        lines.append(f"update_note: {batch.update_note}")

    lines.extend(["", "# Statements", ""])

    used_ids: Dict[str, int] = {}
    for entry in batch.entries:
        statement_id = _entry_id(entry, batch, used_ids)
        when = entry.when or batch.default_when or "unknown"
        sort_date = entry.sort_date or batch.default_sort_date
        title = entry.title or entry.heading
        source_type = entry.source_type or batch.default_source_type
        source_link = entry.source_link or batch.default_source_link
        topics = entry.topics or batch.default_topics
        tags = entry.tags or batch.default_tags
        source_refs = _merge_refs(batch.default_source_refs, entry.source_refs, source_link)

        lines.append(f"## {statement_id}")
        lines.append(f"when: {when}")
        if sort_date:
            lines.append(f"sort_date: {sort_date}")
        if title:
            lines.append(f"title: {title}")
        if source_type:
            lines.append(f"source_type: {source_type}")
        if source_link:
            lines.append(f"source_link: {source_link}")
        if source_refs:
            lines.append("source_refs:")
            for ref in source_refs:
                lines.append(f"- {ref}")
        if topics:
            lines.append(f"topics: {' | '.join(topics)}")
        if tags:
            lines.append(f"tags: {' | '.join(tags)}")
        if entry.summary:
            lines.append(f"summary: {entry.summary}")
        if entry.stance:
            lines.append(f"stance: {entry.stance}")
        if entry.canonical is not None:
            lines.append(f"canonical: {'true' if entry.canonical else 'false'}")
        lines.append("text:")
        for text_line in entry.text.splitlines():
            if text_line:
                lines.append(f"> {text_line}")
            else:
                lines.append(">")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_entry(data: Dict[str, object], path: Path) -> BatchEntry:
    return BatchEntry(
        heading=_required_value(data, "heading", path),
        id=_optional_text(data.get("id")),
        when=_optional_text(data.get("when")),
        sort_date=_optional_text(data.get("sort_date")),
        title=_optional_text(data.get("title")),
        summary=_optional_text(data.get("summary")),
        source_type=_optional_text(data.get("source_type")),
        source_link=_optional_text(data.get("source_link")),
        source_refs=_coerce_list(data.get("source_refs")),
        topics=_coerce_list(data.get("topics")),
        tags=_coerce_list(data.get("tags")),
        stance=_optional_text(data.get("stance")),
        canonical=_coerce_bool(data.get("canonical")),
        text=_required_value(data, "text", path),
    )


def _parse_metadata(
    target: Dict[str, object],
    line: str,
    path: Path,
    lineno: int,
    current_list_key: Optional[str],
) -> Optional[str]:
    if current_list_key and line.startswith("- "):
        items = target.setdefault(current_list_key, [])
        if not isinstance(items, list):
            raise FormatError(f"{path}:{lineno}: field '{current_list_key}' must be a list")
        items.append(line[2:].strip())
        return current_list_key

    match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s*(.*))?$", line)
    if not match:
        raise FormatError(f"{path}:{lineno}: invalid metadata line '{line}'")
    key = match.group(1)
    value = (match.group(2) or "").strip()
    if key in BATCH_LIST_FIELDS:
        if value:
            target[key] = [item.strip() for item in value.split("|") if item.strip()]
            return None
        else:
            target[key] = []
            return key
    if key == "canonical":
        target[key] = value.lower() in {"1", "true", "yes"} if value else None
        return None
    target[key] = value
    return None


def _looks_like_metadata(line: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*.*$", line))


def _normalize_body(lines: List[str]) -> str:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    normalized: List[str] = []
    for line in lines:
        if line.startswith("> "):
            normalized.append(line[2:])
        elif line == ">":
            normalized.append("")
        else:
            normalized.append(line)
    return "\n".join(normalized).strip()


def _is_horizontal_rule(line: str) -> bool:
    return bool(re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", line))


def _required_value(data: Dict[str, object], key: str, path: Path) -> str:
    value = _optional_text(data.get(key))
    if not value:
        raise FormatError(f"{path}: missing required field '{key}'")
    return value


def _optional_text(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_list(value: object) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split("|") if item.strip()]


def _coerce_bool(value: object) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def _apply_import_options(batch: BatchDocument, options: ImportOptions) -> BatchDocument:
    return BatchDocument(
        path=batch.path,
        person_slug=options.person_slug or batch.person_slug,
        update_note=options.update_note or batch.update_note,
        default_when=options.default_when or batch.default_when,
        default_sort_date=options.default_sort_date or batch.default_sort_date,
        default_source_type=options.default_source_type or batch.default_source_type,
        default_source_link=options.default_source_link or batch.default_source_link,
        default_topics=options.default_topics or batch.default_topics,
        default_tags=options.default_tags or batch.default_tags,
        default_source_refs=options.default_source_refs or batch.default_source_refs,
        entries=batch.entries,
    )


def _entry_id(entry: BatchEntry, batch: BatchDocument, used_ids: Dict[str, int]) -> str:
    if entry.id:
        candidate = entry.id
    else:
        time_part = _id_time_fragment(entry.when or batch.default_when or "unknown")
        title_part = slugify(entry.title or entry.heading)
        candidate = f"{time_part}-{title_part}".strip("-")
    seen = used_ids.get(candidate, 0)
    used_ids[candidate] = seen + 1
    if seen == 0:
        return candidate
    return f"{candidate}-{seen + 1}"


def _infer_heading_from_line(line: str) -> str:
    text = line.strip()
    if text.startswith("> "):
        text = text[2:]
    elif text.startswith(">"):
        text = text[1:].strip()
    if text.startswith("- "):
        text = text[2:]
    if len(text) <= 80:
        return text or "Untitled statement"
    compact = " ".join(text.split())
    if len(compact) <= 80:
        return compact
    return compact[:77].rstrip() + "..."


def _id_time_fragment(value: str) -> str:
    if not value or value == "unknown":
        return "unknown"
    cleaned = value.lower()
    cleaned = cleaned.replace("t", "-").replace(":", "-").replace("+", "-").replace("/", "-")
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "unknown"


def _merge_refs(defaults: List[str], entry_refs: List[str], source_link: Optional[str]) -> List[str]:
    refs: List[str] = []
    for ref in defaults + entry_refs:
        if ref not in refs:
            refs.append(ref)
    if source_link and source_link not in refs:
        refs.append(source_link)
    return refs


def _resolve_output_path(output_path: Path, person_slug: str) -> Path:
    if output_path.suffix == ".md":
        return output_path
    filename = f"{date.today().isoformat()}-{person_slug}-import.md"
    return output_path / filename
