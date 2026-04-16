# Plugin Install

`llm-wiki` 分成两层：

- `llm-wiki` CLI：负责生成、导入、自动补 topics、重建 wiki
- `llm-wiki-mcp`：负责让 agent 以只读方式消费生成后的 wiki

## 1. 安装项目

```bash
git clone https://github.com/mango8853/agent-llm-wiki.git
cd agent-llm-wiki
python3 -m pip install -e ".[mcp]"
```

## 2. 先构建一个公开 sample

```bash
llm-wiki build \
  --source examples/trader-sample.md
```

这会生成：

```text
~/.llm-wiki/wikis/trader-sample/
```

如果你要给自己的私有资料建库，也建议把原始文件放在本地忽略路径里，然后让 agent 或 CLI 直接 build 到默认库目录。

你也可以不 build，直接把一个现成 wiki 文件夹复制到：

```text
~/.llm-wiki/wikis/
```

插件会把带有 `index.md` 和 `WIKI_AGENT.md` 的子目录识别成已安装 wiki。

## 3. 直接启动 MCP server

```bash
llm-wiki-mcp
```

默认会暴露这些只读工具：

- `list_people`
- `get_library_guide`
- `get_index`
- `get_wiki_guide`
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
      "args": []
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

这版插件默认就会读 `~/.llm-wiki/wikis`，所以正常情况下不需要再改路径。

## 6. 推荐 agent 读取顺序

1. 先 `get_library_guide()`
2. 再 `list_people()`
3. 选中人物后调用 `get_wiki_guide(person_slug)`
4. 再按问题调用 `get_topic_statements(...)` 或 `search_statements(...)`
5. 需要完整出处时再 `get_sources(...)` 或 `get_statement(...)`

这样比直接读取整份超长 topic markdown 更稳。
