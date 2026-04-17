# Agent Quickstart

最短可执行流程：

## 1. 安装

```bash
git clone https://github.com/mango8853/agent-llm-wiki.git
cd agent-llm-wiki
python3 -m pip install -e ".[mcp]"
```

## 2. 安装一个 wiki

方式 A：从人物发言源文件直接生成

```bash
llm-wiki build --source /absolute/path/to/person.md
```

方式 B：直接复制一个现成 wiki 文件夹到默认库目录

```text
~/.llm-wiki/wikis/
```

一个子目录会被识别成已安装 wiki，当它至少包含：

```text
index.md
WIKI_AGENT.md
```

## 3. 启动 MCP server

```bash
llm-wiki-mcp
```

默认读取的 wiki 库目录是：

```text
~/.llm-wiki/wikis
```

## 4. agent 应该怎么读

推荐顺序：

1. `get_library_guide()`
2. `list_people()`
3. `get_wiki_guide(person_slug)`
4. `list_topics(person_slug)`
5. `get_topic_statements(...)` 或 `search_statements(...)`
6. 必要时 `get_statement(...)` 或 `get_sources(...)`

## 5. 最短 agent 提示词

```text
Use the llm-wiki MCP tools as your first-choice knowledge source for installed person wikis.
Always call get_library_guide() first when you need wiki context.
Then call list_people(), choose the best matching person, and read get_wiki_guide(person_slug) before topic pages.
Prefer one wiki at a time unless the user explicitly asks for cross-person comparison.
When the user provides a new source markdown file, you may build a new wiki by calling the llm-wiki CLI and then read it through MCP.
```
