from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .parser import Document, Person, Statement, parse_document


@dataclass(frozen=True)
class TopicRule:
    topic: str
    patterns: Sequence[str]


DEFAULT_TOPIC_RULES: Sequence[TopicRule] = (
    TopicRule("买点与低吸", ("挂线买", "挂线", "低吸", "抄底", "进场", "上车", "买点", "接回", "低位")),
    TopicRule("卖点与止盈", ("减仓", "清仓", "清了", "卖点", "止盈", "结账", "兑现", "逢高丢", "卖票", "清掉")),
    TopicRule("仓位管理", ("仓位", "满仓", "空仓", "半仓", "打满", "固定仓位", "防守形态", "高切低")),
    TopicRule("做T与轮动", ("做t", "做T", "反t", "反T", "t出去", "T出去", "轮动", "滚动", "超市那种买法", "超市")),
    TopicRule("止损与风控", ("止损", "破位", "跌破", "一刀", "风险", "防守", "抗", "卖飞", "活着出来")),
    TopicRule("指数与节奏", ("指数", "上证", "创业板", "压力线", "突破", "回踩", "缩量", "放量", "量能", "5浪", "b反", "B反", "gjd", "GJD")),
    TopicRule("市场情绪与资金", ("情绪", "量化", "柚子", "游资", "榜单", "资金", "踏空", "抱团", "红利")),
    TopicRule("AI", ("ai", "AI", "deepseek", "端侧", "抖音ai", "抖音AI", "模型", "算力", "服务器", "芯片", "cpo", "CPO", "pcb", "PCB")),
    TopicRule("机器人", ("机器人", "丝杠", "灵巧手", "减速器", "三花", "兆威", "北特", "五洲新春")),
    TopicRule("算力与芯片", ("算力", "芯片", "服务器", "pcb", "PCB", "cpo", "CPO", "中兴", "光模块", "交换机", "端侧芯片")),
    TopicRule("稀土", ("稀土",)),
    TopicRule("电池", ("电池", "固态", "伏特", "东鹏")),
    TopicRule("医药", ("创新药", "医药", "药 ")),
)


def autotag_source(
    source_path: Path,
    output_path: Optional[Path] = None,
    *,
    replace_existing: bool = False,
    max_topics: int = 4,
) -> Dict[str, object]:
    document = parse_document(source_path)
    rendered = render_document_with_topics(document, replace_existing=replace_existing, max_topics=max_topics)
    destination = output_path or source_path
    destination.write_text(rendered, encoding="utf-8")

    topic_counter: Dict[str, int] = {}
    tagged_count = 0
    for statement in document.statements:
        final_topics = infer_topics(statement, max_topics=max_topics) if replace_existing or not statement.topics else statement.topics
        if final_topics:
            tagged_count += 1
        for topic in final_topics:
            topic_counter[topic] = topic_counter.get(topic, 0) + 1

    return {
        "output_path": str(destination),
        "statement_count": len(document.statements),
        "tagged_statements": tagged_count,
        "topic_count": len(topic_counter),
        "top_topics": sorted(topic_counter.items(), key=lambda item: (-item[1], item[0]))[:20],
    }


def render_document_with_topics(
    document: Document,
    *,
    replace_existing: bool = False,
    max_topics: int = 4,
) -> str:
    lines: List[str] = []
    if document.person is not None:
        lines.extend(_render_person(document.person))
    else:
        lines.extend(_render_increment_header(document.person_slug or "", document.update_note))
    lines.extend(["", "# Statements", ""])

    for statement in document.statements:
        inferred = infer_topics(statement, max_topics=max_topics)
        topics = inferred if replace_existing or not statement.topics else statement.topics
        lines.extend(_render_statement(statement, topics))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def infer_topics(statement: Statement, *, max_topics: int = 4) -> List[str]:
    search_text = "\n".join(
        part for part in [
            statement.title or "",
            statement.summary or "",
            statement.text,
            "\n".join(statement.notes),
        ] if part
    )
    hits: List[str] = []
    for rule in DEFAULT_TOPIC_RULES:
        if any(_matches(pattern, search_text) for pattern in rule.patterns):
            hits.append(rule.topic)

    if not hits and statement.source_type == "forum":
        hits.append("盘面交流")

    deduped: List[str] = []
    for topic in hits:
        if topic not in deduped:
            deduped.append(topic)
        if len(deduped) >= max_topics:
            break
    return deduped


def _matches(pattern: str, text: str) -> bool:
    if any(char.isalpha() for char in pattern):
        return pattern.lower() in text.lower()
    return pattern in text


def _render_person(person: Person) -> List[str]:
    return [
        "# Person",
        f"name: {person.name}",
        f"slug: {person.slug}",
        f"aliases: {' | '.join(person.aliases)}" if person.aliases else "aliases:",
        f"description: {person.description}" if person.description else "description:",
    ]


def _render_increment_header(person_slug: str, update_note: Optional[str]) -> List[str]:
    lines = ["# Increment", f"person_slug: {person_slug}"]
    if update_note:
        lines.append(f"update_note: {update_note}")
    return lines


def _render_statement(statement: Statement, topics: Sequence[str]) -> List[str]:
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
    if topics:
        lines.append(f"topics: {' | '.join(topics)}")
    if statement.tags:
        lines.append(f"tags: {' | '.join(statement.tags)}")
    if statement.summary:
        lines.append(f"summary: {statement.summary}")
    if statement.stance:
        lines.append(f"stance: {statement.stance}")
    if statement.claims:
        lines.append("claims:")
        for claim in statement.claims:
            lines.append(f"- {claim}")
    if statement.notes:
        lines.append("notes:")
        for note in statement.notes:
            lines.append(f"- {note}")
    if statement.canonical:
        lines.append("canonical: true")
    lines.append("text:")
    for text_line in statement.text.splitlines():
        lines.append(f"> {text_line}" if text_line else ">")
    return lines
