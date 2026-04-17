# llm-wiki

把“某个人公开发言的 markdown 资料”编译成一个可持续增量更新的 markdown wiki，并生成一份给 agent 用的 `WIKI_AGENT.md`。

这版 schema 已经按“人物语录档案”做过一轮收敛：

- 原文必须直接放进每条 statement
- 时间允许精确到秒，也允许 `unknown`
- `source_type`、`title`、`source_link`、`summary` 都不是必填
- 一个 statement 可以挂多个本地或远端来源

## 1. 能力概览

输入：

- 1 个基础人物发言文件
- 0 到 N 个增量更新文件

输出：

- `index.md`：人物总览
- `timeline.md`：按时间组织的发言
- `topics/*.md`：按主题组织的发言
- `sources.md`：来源目录
- `log.md`：构建日志
- `WIKI_AGENT.md`：给 LLM / agent 的阅读与引用约定
- `_meta/*.json`：机器可读清单，方便后续接 API 或检索

完整形态现在是：

- `CLI` 负责写：导入、增量、自动打 topics、重建 wiki
- `MCP` 负责读：让 agent 只读访问已生成的 wiki

## 2. 安装

```bash
git clone https://github.com/mango8853/agent-llm-wiki.git
cd agent-llm-wiki
python3 -m pip install -e .
```

安装后会得到一个命令：

```bash
llm-wiki
```

默认的 wiki 库目录是：

```text
~/.llm-wiki/wikis
```

这意味着：

- 你可以直接让 agent 调 `llm-wiki build --source <人物源文件.md>`，生成结果会默认落到这个库目录
- 你也可以手动把一个现成 wiki 文件夹复制到这个目录里
- 只要子目录里有 `index.md` 和 `WIKI_AGENT.md`，插件就会把它识别成一个可读 wiki

如果你只想要最短安装说明，直接看：

- `docs/AGENT_QUICKSTART.md`

也可以不安装，直接这样跑：

```bash
PYTHONPATH=src python3 -m llm_wiki.cli --help
```

如果你手上已经有“一个长 markdown 摘录文件”，也可以先转成增量文件：

```bash
llm-wiki import-batch \
  --input examples/raw/yamada-batch.md \
  --output examples/generated
```

如果手里的文件更野一点，没有 `# Batch` 头，也可以这样补必要默认值：

```bash
llm-wiki import-batch \
  --input examples/raw/yamada-wild.md \
  --output examples/generated \
  --person-slug yamada-anna \
  --default-source-ref examples/raw/yamada-wild.md
```

如果你的爬虫脚本是一条条推送，也可以直接 ingest 单条 JSON：

```bash
echo '{
  "person_slug": "yamada-anna",
  "when": "2026-04-16T21:00:00+08:00",
  "topics": ["agents", "evals"],
  "source_refs": ["raw/live-feed.md#L120"],
  "text": "If you cannot measure the behavior, you cannot improve the agent."
}' | llm-wiki ingest-statement \
  --increments examples/live-increments
```

如果你的远端爬虫是 NGA `posts.md` 持续增长，仓库里也可以直接用轮询脚本：

```bash
PYTHONPATH=src python3 scripts/langda_ingest.py \
  --poll-seconds 600
```

这版脚本默认会直接读：

- `/home/mango/nga_spider/nga_downloads/自立自强，科学技术打头阵/posts.md`

并自动维护：

- `/home/mango/.llm-wiki/sources/langda/langda_feed.md`
- `/home/mango/.llm-wiki/sources/langda/increments/`
- `/home/mango/.llm-wiki/wikis/langda/`

推荐做法是：

- `langda.md` 保持为稳定的基础人物文件
- `langda_ingest.py` 负责从 `posts.md` 抽出狼大的新发言并写进 `langda_feed.md`
- 然后只把“没见过的新 statement”转成 increment，再重建 wiki

这样不会让基础源文件和增量目录变成两套重复事实源。

如果一份人物源文件已经整理好了，但还没打 `topics`，可以直接自动补：

```bash
llm-wiki autotag-topics \
  --source examples/trader-sample.md \
  --replace-existing
```

如果你要把它接给 agent，用 MCP server：

```bash
python3 -m pip install -e ".[mcp]"
llm-wiki-mcp
```

## 3. 基础人物发言文件格式

基础文件必须包含 `# Person` 和 `# Statements` 两个 section。

示例：

```md
# Person
name: Yamada Anna
slug: yamada-anna
aliases: Anna | Yamada
description: AI researcher, educator, and builder.

# Statements

## x-2025-02-15-context-engineering
when: 2025-02-15T09:30:00+08:00
sort_date: 2025-02-15T09:30:00+08:00
title: Context engineering
source_refs:
- raw/yamada-notes.md#L10
- https://example.com/post/1
topics: context engineering | agents | prompting
summary: He reframes prompt engineering as context engineering for production agents.
stance: positive
text:
> Context engineering is the delicate art and science of filling the context window.
claims:
- Prompt engineering is too narrow for modern agents.
- The real work is assembling the right context window.
notes:
- This is a good seed statement for the terminology topic.
canonical: true
```

### 字段约定

- `name`：人物名称，必填
- `slug`：人物目录名，可选；不写会自动生成
- `aliases`：别名，用 ` | ` 分隔
- `description`：人物简介，可选

每条 statement 现在只强制要求 2 个字段：

- `## <statement-id>`：唯一 ID，必填
- `text`：原始发言内容，必填

时间字段是宽松的：

- `when`：展示给人看的时间，可以是 `2026-04-16`、`2026-04-16T10:35:00+08:00`、`2026-04`、`2026`、`circa 2012`、`unknown`
- `sort_date`：可选。只有当 `when` 不是可排序的 ISO 时间时才建议填写，比如 `when: circa 2012` 时，可以写 `sort_date: 2012`

可选字段：

- `title`
- `source_type`
- `source_link`
- `source_refs`
- `tags`
- `topics`
- `summary`
- `stance`
- `claims`
- `excerpt`
- `notes`
- `canonical`

说明：

- `source_type` 现在不是必填了，只是补充信息
- `title` 不是必填，不写就会用 `summary` 或原文前几句自动生成标签
- `source_link` 不是必填；如果你只想用本地文件，也完全没问题
- `source_refs` 用来记录一个或多个来源定位，比如本地整理文件、原始摘录文件、网页链接
- `topics` 用来把人物 wiki 自动分主题页，不写也能用，只是会落到 `uncategorized`
- `summary` 是给长段材料做一句话提炼的，不是每条都必须有；如果原文本来就只有一句，完全可以不写
- 原文直接放在 `text` 字段里，生成的 wiki 页面会把原文内嵌进去，不需要每次再回头翻源文件

## 4. 增量文件格式

增量文件用来追加新发言，必须包含 `# Increment` 和 `# Statements`。

示例：

```md
# Increment
person_slug: yamada-anna
update_note: Add remarks from a new podcast episode.

# Statements

## podcast-2026-04-10-evals
when: unknown
sort_date: 2026-04
source_refs:
- raw/podcast-episode-9.md#L88
topics: evals | agents | product
summary: He argues that evals are the main control surface for reliable agent products.
text:
> If you can't measure the behavior, you can't improve the agent.
claims:
- Teams should treat evals as product infrastructure.
```

说明：

- `person_slug` 必须和基础文件中的 `slug` 对齐
- 如果增量文件里的 statement ID 已存在，会覆盖旧内容
- 你可以把增量文件放在一个目录里，构建时批量 ingest
- 对于旧人物、史料不完整的人物，最推荐写法是 `when: unknown`，然后如果你大概知道年代，再补一个 `sort_date: 1898` 或 `sort_date: 1898-06`

## 5. 使用方式

校验基础文件：

```bash
llm-wiki check --source examples/yamada-anna.md
```

构建 wiki：

```bash
llm-wiki build \
  --source examples/yamada-anna.md \
  --increments examples/increments \
  --output dist
```

构建完成后，你会得到：

```text
dist/
  yamada-anna/
    WIKI_AGENT.md
    index.md
    timeline.md
    sources.md
    log.md
    topics/
      agents.md
      context-engineering.md
      evals.md
```

如果你只想先从一个基础文件开始，也可以不传 `--increments`。

如果你希望“写入单条增量后立刻重建 wiki”，可以这样：

```bash
cat payload.json | llm-wiki ingest-statement \
  --increments examples/live-increments \
  --source examples/yamada-anna.md \
  --build-output dist
```

这很适合爬虫、监听脚本、Webhook consumer 持续推送新发言。

## 6. 长 markdown 批量导入

如果你已经整理好一个长 `md` 文件，最方便的方式是写成下面这种批量格式，再用 `import-batch` 转成标准增量文件。

示例：

```md
# Batch
person_slug: yamada-anna
update_note: Import a note dump collected from one long markdown file.
default_when: unknown
default_source_refs: raw/yamada-batch.md

# Entries

## Context engineering
when: 2025-02-15
topics: context engineering | agents | prompting
summary: He reframes prompt engineering as context engineering for production agents.

> Context engineering is the delicate art and science of filling the context window.

## Shipping beats elegant demos
when: 2023-11-21
topics: product | evals | agents

The way to learn is to build and ship.
```

规则：

- `# Batch` 里放默认值，比如 `person_slug`、`default_when`、`default_source_refs`
- `# Entries` 下每个 `## 标题` 都会被切成一条 statement
- 每个 entry 开头可以写少量 metadata 行，比如 `when:`、`topics:`、`summary:`
- metadata 后面的正文会被当作原文 `text`
- 正文可以是普通段落，也可以是 `>` 引用块
- `id` 可以不写，导入器会按时间和标题自动生成唯一 ID

转换命令：

```bash
llm-wiki import-batch \
  --input examples/raw/yamada-batch.md \
  --output examples/generated
```

生成后你会得到一个标准增量文件，然后可以继续：

```bash
llm-wiki build \
  --source examples/yamada-anna.md \
  --increments examples/generated \
  --output dist
```

更野生的格式也支持几类常见写法：

- 没有 `# Batch` / `# Entries`，只有 `## 小标题 + 正文`
- 用 `---` 把多条摘录分块
- 一条摘录前面先写几行 metadata，再接正文
- 只有引用块或普通段落，没有显式标题，导入器会用正文前一段自动生成标题

对于这类松散文件，最稳的命令是：

```bash
llm-wiki import-batch \
  --input your-wild-notes.md \
  --output generated \
  --person-slug your-person \
  --default-source-ref your-wild-notes.md \
  --default-when unknown
```

## 7. 为什么有 `topics` 和 `summary`

`topics` 的目的不是“凑字段”，而是让人物 wiki 自动长出按主题组织的页面。这样 agent 回答“他怎么看 evals”时，不用把所有发言全扫一遍，而是优先看 `topics/evals.md`。

`summary` 的目的也不是必须每条都写，而是给长材料压缩出一句高密度摘要，方便 `index.md` 和浏览。只有一句原话时，完全可以不写 summary。

如果你懒得手工维护 `topics`，项目内置了一个规则版自动打标器，适合先把大批交易发言拆成这些常用主题：

- `买点与低吸`
- `卖点与止盈`
- `仓位管理`
- `做T与轮动`
- `止损与风控`
- `指数与节奏`
- `市场情绪与资金`
- `AI`
- `机器人`
- `算力与芯片`

这套规则是启发式的，够用来把大文件拆成多个主题页，但不等于完美语义理解。

## 8. MCP Server

项目内置了一个只读 MCP server，适合让 agent 在回答时按需读取 wiki，而不是整页硬吞。

可用工具包括：

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

推荐 agent 的读取顺序：

1. `get_library_guide()`
2. `list_people()`
3. 选中人物后调用 `get_wiki_guide(person_slug)`
4. `list_topics(person_slug)`
5. `get_topic_statements(...)` 或 `search_statements(...)`
6. 必要时 `get_statement(...)` 或 `get_sources(...)`

## 9. Plugin Install

仓库里已经带了一个本地 Codex 插件清单：

- `plugins/llm-wiki/.codex-plugin/plugin.json`
- `plugins/llm-wiki/.mcp.json`

更完整的安装步骤在：

- `docs/AGENT_QUICKSTART.md`
- `docs/PLUGIN_INSTALL.md`

## 10. 推荐接入远端 agent 的方式

最简单的接法：

1. 把构建产物目录同步到远端机器
2. 让远端 agent 在回答问题时先读 `index.md`
3. 再按主题去 `topics/*.md`
4. 需要精确引用时先看每条 statement 自带的原文，再用 `sources.md` 追溯到源文件

生成的 `WIKI_AGENT.md` 已经把这套规则写好了。

## 11. 公开 sample 与私有资料

仓库里的公开 sample 只包含可以开源分发的示例材料：

- `examples/yamada-anna.md`
- `examples/trader-sample.md`
- `examples/raw/yamada-batch.md`
- `examples/raw/yamada-wild.md`
- `examples/raw/trader-sample-notes.md`

如果你本地还有不适合发布的人物资料，建议放在忽略路径里，不要把它们作为仓库 sample 提交。更推荐的实际使用方式是：

- 源文件放你自己管理的位置
- 让 agent 调 `llm-wiki build --source /path/to/person.md`
- 或者直接把一个现成 wiki 文件夹复制进 `~/.llm-wiki/wikis/`

运行一个公开示例：

```bash
llm-wiki build \
  --source examples/trader-sample.md
```

然后打开：

- `~/.llm-wiki/wikis/trader-sample/index.md`
- `~/.llm-wiki/wikis/trader-sample/topics/risk-management.md`
- `~/.llm-wiki/wikis/trader-sample/WIKI_AGENT.md`

## 12. 开发与测试

运行测试：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
