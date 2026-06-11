# AutoSkill Core：SDK、运行时与离线抽取

[English](README.md) | 中文

项目主页：[../README.zh-CN.md](../README.zh-CN.md)

本文档聚焦 `autoskill/` 核心包本身：SDK 接口、在线检索与技能演化、Web UI / Proxy 运行时，以及从历史对话和智能体轨迹执行离线技能抽取。

## 目录

- [1. 快速开始](#1-快速开始)
  - [1.1 Web UI](#11-web-ui)
  - [1.2 标准 API 代理](#12-标准-api-代理)
  - [1.3 一键部署（Docker Compose）](#13-一键部署docker-compose)
- [2. 核心工作流](#2-核心工作流)
  - [2.1 学习与进化](#21-学习与进化)
  - [2.2 检索与回答](#22-检索与回答)
  - [2.3 交互抽取策略](#23-交互抽取策略)
  - [2.4 代理服务流程](#24-代理服务流程)
- [3. SkillBank 存储结构](#3-skillbank-存储结构)
- [4. 包结构说明](#4-包结构说明)
  - [4.1 SDK 核心模块](#41-sdk-核心模块)
  - [4.2 Skill Management 层](#42-skill-management-层)
  - [4.3 Interactive 层](#43-interactive-层)
  - [4.4 Offline 层](#44-offline-层)
  - [4.5 示例入口](#45-示例入口)
- [5. SDK 与离线使用](#5-sdk-与离线使用)
  - [5.1 Python SDK](#51-python-sdk)
  - [5.2 导入 OpenAI 对话并自动抽取技能](#52-导入-openai-对话并自动抽取技能)
  - [5.3 通过 CLI 执行离线对话抽取](#53-通过-cli-执行离线对话抽取)
  - [5.4 通过 CLI 执行离线轨迹抽取](#54-通过-cli-执行离线轨迹抽取)
- [6. Provider 配置](#6-provider-配置)
  - [6.1 百炼 DashScope（示例）](#61-百炼-dashscope示例)
  - [6.2 GLM（BigModel）](#62-glmbigmodel)
  - [6.3 OpenAI / Anthropic](#63-openai--anthropic)
  - [6.4 InternLM（Intern-S1 Pro）](#64-internlmintern-s1-pro)
  - [6.5 通用 URL 后端](#65-通用-url-后端)
- [7. 运行工作流与 API](#7-运行工作流与-api)
  - [7.1 终端交互](#71-终端交互)
  - [7.2 Web UI](#72-web-ui)
  - [7.3 启动时离线维护](#73-启动时离线维护)
  - [7.4 OpenAI 兼容代理 API](#74-openai-兼容代理-api)
  - [7.5 自动评测脚本](#75-自动评测脚本)

## 1. 快速开始

### 1.1 Web UI

```bash
python3 -m pip install -e .
export INTERNLM_API_KEY="YOUR_INTERNLM_API_KEY"
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.web_ui \
  --host 127.0.0.1 \
  --port 8000 \
  --llm-provider internlm \
  --embeddings-provider qwen \
  --store-dir SkillBank \
  --user-id u1 \
  --skill-scope all \
  --rewrite-mode always \
  --extract-mode auto \
  --extract-turn-limit 1 \
  --min-score 0.4 \
  --top-k 1
```

启动后打开 `http://127.0.0.1:8000`。

### 1.2 标准 API 代理

AutoSkill 也可以作为反向代理部署，对外暴露 OpenAI 兼容接口，并在内部自动执行：
- 每次对话请求的技能检索与注入
- 回答后的异步技能抽取与维护

```bash
python3 -m pip install -e .
export INTERNLM_API_KEY="YOUR_INTERNLM_API_KEY"
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.openai_proxy \
  --host 127.0.0.1 \
  --port 9000 \
  --llm-provider internlm \
  --embeddings-provider qwen \
  --served-model intern-s1-pro \
  --served-model gpt-5.2 \
  --store-dir SkillBank \
  --skill-scope all \
  --rewrite-mode always \
  --min-score 0.4 \
  --top-k 1
```

支持端点：
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`
- `GET /health`

流式聊天示例：

```bash
curl -N http://127.0.0.1:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "intern-s1-pro",
    "stream": true,
    "messages": [
      {"role": "user", "content": "请简要总结技能自进化的核心思路。"}
    ]
  }'
```

### 1.3 一键部署（Docker Compose）

```bash
cp .env.example .env
# 编辑 .env，填写 API Key
docker compose up --build -d
```

启动后访问：
- Web UI：`http://127.0.0.1:8000`
- API Proxy：`http://127.0.0.1:9000`

停止服务：

```bash
docker compose down
```

## 2. 核心工作流

### 2.1 学习与进化

```text
经验数据（messages/events）
  -> 技能抽取（candidate）
  -> 技能维护（add / merge / discard）
  -> 技能存储（Agent Skill + 向量索引）
```

- 每次尝试最多产出一个高质量候选技能。
- 维护阶段先检查相似技能，再决定新增、合并或丢弃。
- 合并后自动递增 patch 版本，形成长期演化轨迹。

### 2.2 检索与回答

```text
当前 Query（含最近上下文）
  -> Query 重写（可选）
  -> 向量化 + 检索
  -> 技能选择与注入
  -> 大模型回答
```

- 检索每轮执行。
- 通过相似度阈值和 `top_k` 控制召回质量。
- 注入上下文前会再做一次筛选。
- Top-1 检索技能在通过 `min_score` 时会作为抽取阶段的辅助身份上下文。
- 回答完成后，检索技能会异步做相关性与实际使用审计。
- 使用计数按用户隔离，并可自动清理长期被检索但未被使用的用户技能。

### 2.3 交互抽取策略

- `extract_mode=auto`：每 `extract_turn_limit` 轮尝试抽取。
- `extract_mode=always`：每轮都尝试抽取。
- `extract_mode=never`：关闭自动抽取。
- `/extract_now [hint]`：对当前上下文立即发起后台抽取。
- 对无稳定纠偏的一次性请求，默认返回不抽取。
- 用户反馈形成稳定偏好或约束时，触发抽取或更新。
- 若已有相似技能，优先合并更新，而非创建重复技能。

### 2.4 代理服务流程

```text
客户端（OpenAI 兼容请求）
  -> AutoSkill Proxy (/v1/chat/completions)
  -> Query 重写 + 技能检索 + 上下文注入
  -> 上游模型生成
  -> 返回响应
  -> 异步技能抽取与维护
```

- 响应时延重点在检索与生成。
- 技能进化异步执行，避免阻塞客户端。

## 3. SkillBank 存储结构

当使用 `store={"provider": "local", "path": "SkillBank"}`：

```text
SkillBank/
  Users/
    <user_id>/
      <skill-slug>/
        SKILL.md
        scripts/          (可选)
        references/       (可选)
        assets/           (可选)
  Common/
    <skill-slug>/SKILL.md
    <library>/<skill-slug>/SKILL.md
  vectors/
    <embedding-signature>.meta.json
    <embedding-signature>.ids.txt
    <embedding-signature>.vecs.f32
  index/
    skills-bm25.*          （BM25 持久化索引文件）
    skill_usage_stats.json （按用户隔离的检索与使用计数）
```

说明：
- `Users/<user_id>`：用户私有技能。
- `Common/`：共享技能库。
- `vectors/`：按 embedding 签名隔离的持久化向量缓存。
- `index/`：BM25 索引和使用统计，用于检索增强与陈旧技能清理。

## 4. 包结构说明

### 4.1 SDK 核心模块

- `client.py`：SDK 对外入口（`ingest`、`search`、`render_context`、导入导出）。
- `config.py`：全局配置模型。
- `models.py`：核心数据结构（`Skill`、`SkillHit` 等）。
- `render.py`：技能上下文渲染。
- `skill_provenance.py`：技能本地来源追踪与版本历史辅助。
- `llm/`：可插拔对话模型后端。
- `embeddings/`：可插拔 embedding 后端。

### 4.2 Skill Management 层

- `management/extraction.py`：技能抽取逻辑与提示词。
- `management/maintenance.py`：新增、合并、丢弃和版本演化决策。
- `management/formats/agent_skill.py`：`SKILL.md` 渲染与解析。
- `management/stores/local.py`：目录存储与向量映射。
- `management/vectors/flat.py`：本地向量索引后端。
- `management/importer.py`：导入外部 Agent Skills。

### 4.3 Interactive 层

- `interactive/app.py`：CLI 交互编排。
- `interactive/session.py`：Web 和 API 可复用会话引擎。
- `interactive/server.py`：OpenAI 兼容反向代理运行时。
- `interactive/rewriting.py`：检索 query 重写。
- `interactive/selection.py`：注入前技能选择。
- `interactive/unified.py`：interactive 与 proxy 的统一组合入口。

### 4.4 Offline 层

- `offline/conversation/extract.py`：导入 OpenAI 标准对话 `.json/.jsonl` 并抽取技能。
- `offline/trajectory/extract.py`：导入智能体轨迹数据并抽取流程型技能。
- `offline/document` 已不属于 `autoskill/`，文档抽取由 [../AutoSkill4Doc/README.zh-CN.md](../AutoSkill4Doc/README.zh-CN.md) 独立维护。

### 4.5 示例入口

- `../examples/web_ui.py`：本地 Web UI 服务。
- `../examples/interactive_chat.py`：终端交互式对话。
- `../examples/openai_proxy.py`：OpenAI 兼容代理入口。
- `../examples/auto_evalution.py`：自动化 LLM-vs-LLM 技能演化评测。
- `../examples/basic_ingest_search.py`：最小 SDK 流程示例。

## 5. SDK 与离线使用

### 5.1 Python SDK

```python
from autoskill import AutoSkill, AutoSkillConfig

sdk = AutoSkill(
    AutoSkillConfig(
        llm={"provider": "mock"},
        embeddings={"provider": "hashing", "dims": 256},
        store={"provider": "local", "path": "SkillBank"},
    )
)

sdk.ingest(
    user_id="u1",
    messages=[
        {"role": "user", "content": "Before each release: run regression -> canary -> monitor -> full rollout."},
        {"role": "assistant", "content": "Understood."},
    ],
)

hits = sdk.search("How should I do a safe release?", user_id="u1", limit=3)
for h in hits:
    print(h.skill.name, h.score)
```

### 5.2 导入 OpenAI 对话并自动抽取技能

```python
from autoskill import AutoSkill, AutoSkillConfig

sdk = AutoSkill(
    AutoSkillConfig(
        llm={"provider": "internlm", "model": "intern-s1-pro"},
        embeddings={"provider": "qwen", "model": "text-embedding-v4"},
        store={"provider": "local", "path": "SkillBank"},
    )
)

result = sdk.import_openai_conversations(
    user_id="u1",
    file_path="./data/openai_dialogues.jsonl",
    hint="Focus on reusable user preferences and workflows.",
    continue_on_error=True,
    max_messages_per_conversation=100,
)

print("processed:", result["processed"], "upserted:", result["upserted_count"])
```

说明：
- 输入建议为 OpenAI 标准对话数据（`.json` / `.jsonl`，包含 `messages`）。
- 抽取时会构造成两部分输入：
  - `Primary User Questions (main evidence)`
  - `Full Conversation (context reference)`
- 用户回合作为主证据；assistant 侧平台信息和产物不作为技能证据。

### 5.3 通过 CLI 执行离线对话抽取

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./data/random_50 \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope
```

行为说明：
- `--file` 支持单个 `.json` / `.jsonl` 文件，或包含多个文件的目录。
- 如果单个 `.json` 文件中包含多个对话，加载器会自动遍历所有对话单元。
- 运行过程中会实时输出文件名和抽取到的技能名。

### 5.4 通过 CLI 执行离线轨迹抽取

```bash
python3 -m autoskill.offline.trajectory.extract \
  --file ./data/traces \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --success-only 1 \
  --include-tool-events 1
```

## 6. Provider 配置

### 6.1 百炼 DashScope（示例）

```bash
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.interactive_chat --llm-provider dashscope
```

### 6.2 GLM（BigModel）

```bash
export ZHIPUAI_API_KEY="YOUR_ID.YOUR_SECRET"
python3 -m examples.interactive_chat --llm-provider glm
```

### 6.3 OpenAI / Anthropic

```bash
export OPENAI_API_KEY="YOUR_OPENAI_KEY"
python3 -m examples.interactive_chat --llm-provider openai

export ANTHROPIC_API_KEY="YOUR_ANTHROPIC_KEY"
python3 -m examples.interactive_chat --llm-provider anthropic
```

### 6.4 InternLM（Intern-S1 Pro）

```bash
export INTERNLM_API_KEY="YOUR_INTERNLM_TOKEN"
python3 -m examples.interactive_chat --llm-provider internlm --llm-model intern-s1-pro
```

### 6.5 通用 URL 后端

```bash
export AUTOSKILL_GENERIC_LLM_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_LLM_MODEL="gpt-5.2"
export AUTOSKILL_GENERIC_EMBED_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_EMBED_MODEL="embd_qwen3vl8b"
export AUTOSKILL_GENERIC_API_KEY=""

python3 -m examples.interactive_chat --llm-provider generic --embeddings-provider generic
```

## 7. 运行工作流与 API

### 7.1 终端交互

```bash
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.interactive_chat --llm-provider dashscope
```

常用命令：
- `/extract_now [hint]`
- `/extract_every <n>`
- `/extract auto|always|never`
- `/scope user|common|all`
- `/search <query>`
- `/skills`
- `/export <skill_id>`

### 7.2 Web UI

```bash
export INTERNLM_API_KEY="YOUR_INTERNLM_API_KEY"
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.web_ui --llm-provider internlm --embeddings-provider qwen
```

### 7.3 启动时离线维护

服务启动（`web_ui`、`interactive_chat`、`openai_proxy`）时，AutoSkill 可自动：
- 检查并补齐 `SKILL.md` 中缺失的 `id:`
- 当配置 `AUTOSKILL_AUTO_IMPORT_DIRS` 时，自动导入外部技能目录

可选环境变量：
- `AUTOSKILL_AUTO_NORMALIZE_IDS`
- `AUTOSKILL_AUTO_IMPORT_DIRS`
- `AUTOSKILL_AUTO_IMPORT_SCOPE`
- `AUTOSKILL_AUTO_IMPORT_LIBRARY`
- `AUTOSKILL_AUTO_IMPORT_OVERWRITE`
- `AUTOSKILL_AUTO_IMPORT_INCLUDE_FILES`
- `AUTOSKILL_AUTO_IMPORT_MAX_DEPTH`

### 7.4 OpenAI 兼容代理 API

```bash
export INTERNLM_API_KEY="YOUR_INTERNLM_API_KEY"
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.openai_proxy --llm-provider internlm --embeddings-provider qwen
```

能力发现：

```bash
curl http://127.0.0.1:9000/v1/autoskill/capabilities
curl http://127.0.0.1:9000/v1/autoskill/openapi.json
```

OpenAI 兼容端点：
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`

技能管理端点：
- `GET /v1/autoskill/skills`
- `GET /v1/autoskill/skills/{skill_id}`
- `GET /v1/autoskill/skills/{skill_id}/md`
- `PUT /v1/autoskill/skills/{skill_id}/md`
- `DELETE /v1/autoskill/skills/{skill_id}`
- `POST /v1/autoskill/skills/{skill_id}/rollback`
- `GET /v1/autoskill/skills/{skill_id}/versions`
- `GET /v1/autoskill/skills/{skill_id}/export`
- `POST /v1/autoskill/skills/search`
- `POST /v1/autoskill/skills/import`
- `POST /v1/autoskill/conversations/import`

检索与抽取端点：
- `POST /v1/autoskill/retrieval/preview`
- `POST /v1/autoskill/extractions`
- `POST /v1/autoskill/extractions/simulate`
- `GET /v1/autoskill/extractions/latest`
- `GET /v1/autoskill/extractions`
- `GET /v1/autoskill/extractions/{job_id}`
- `GET /v1/autoskill/extractions/{job_id}/events`

### 7.5 自动评测脚本

```bash
python3 -m examples.auto_evalution \
  --mode eval \
  --eval-strategy evolution \
  --base-url http://127.0.0.1:9000 \
  --sim-provider qwen \
  --sim-api-key "$AUTOSKILL_PROXY_API_KEY" \
  --sim-model qwen-plus \
  --judge-provider qwen \
  --judge-model qwen-plus \
  --judge-api-key "$AUTOSKILL_PROXY_API_KEY" \
  --report-json ./proxy_eval_report.json
```
