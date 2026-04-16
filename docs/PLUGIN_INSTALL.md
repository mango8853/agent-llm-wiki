# Plugin Install

`llm-wiki` 分成两层：

- `llm-wiki` CLI：负责生成、导入、自动补 topics、重建 wiki
- `llm-wiki-mcp`：负责让 agent 以只读方式消费生成后的 wiki

## 1. 安装项目

```bash
git clone https://github.com/<your-user>/llm-wiki.git
cd llm-wiki
python3 -m pip install -e ".[mcp]"
```

## 2. 先构建 wiki

```bash
llm-wiki build \
  --source examples/langda.md \
  --output dist
```

这会生成：

```text
dist/langda/
```

## 3. 直接启动 MCP server

```bash
llm-wiki-mcp --wiki-root /absolute/path/to/llm-wiki/dist
```

默认会暴露这些只读工具：

- `list_people`
- `get_index`
- `get_agents_guide`
- `list_topics`
- `get_topic_page`
- `get_topic_statements`
- `get_timeline`
- `get_sources`
- `search_statements`
- `get_recent_statements`
- `get_statement`

## 4. 通用 MCP 配置示例

```json
{
  "mcpServers": {
    "llm-wiki": {
      "command": "llm-wiki-mcp",
      "args": [],
      "env": {
        "LLM_WIKI_ROOT": "/absolute/path/to/llm-wiki/dist"
      }
    }
  }
}
```

## 5. Codex 本地插件

仓库里已经包含一个本地插件清单：

```text
plugins/llm-wiki/.codex-plugin/plugin.json
plugins/llm-wiki/.mcp.json
```

把 `plugins/llm-wiki/.mcp.json` 里的 `LLM_WIKI_ROOT` 改成你的实际 wiki 根目录即可。

## 6. 推荐 agent 读取顺序

1. 先 `get_index(person_slug)`
2. 再 `list_topics(person_slug)`
3. 按问题调用 `get_topic_statements(...)` 或 `search_statements(...)`
4. 需要完整出处时再 `get_sources(...)` 或 `get_statement(...)`

这样比直接读取整份超长 topic markdown 更稳。
