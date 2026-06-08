# AutoSkill Core: SDK, Runtime, and Offline Extraction

English | [中文](README.zh-CN.md)

Project Root: [../README.md](../README.md)

This document focuses on the core `autoskill/` package: SDK APIs, online retrieval and skill evolution, Web UI / proxy runtime, and offline extraction from archived conversations and agentic trajectories.

## Table of Contents

- [1. Quick Start](#1-quick-start)
  - [1.1 Web UI](#11-web-ui)
  - [1.2 Standard API Proxy](#12-standard-api-proxy)
  - [1.3 One-click Deploy (Docker Compose)](#13-one-click-deploy-docker-compose)
- [2. Core Workflow](#2-core-workflow)
  - [2.1 Ingest and Evolve](#21-ingest-and-evolve)
  - [2.2 Retrieve and Respond](#22-retrieve-and-respond)
  - [2.3 Interactive Extraction Policy](#23-interactive-extraction-policy)
  - [2.4 Proxy Serving Flow](#24-proxy-serving-flow)
- [3. SkillBank Storage Layout](#3-skillbank-storage-layout)
- [4. Package Structure](#4-package-structure)
  - [4.1 Core SDK Modules](#41-core-sdk-modules)
  - [4.2 Skill Management Layer](#42-skill-management-layer)
  - [4.3 Interactive Layer](#43-interactive-layer)
  - [4.4 Offline Layer](#44-offline-layer)
  - [4.5 Example Entrypoints](#45-example-entrypoints)
- [5. SDK and Offline Usage](#5-sdk-and-offline-usage)
  - [5.1 Python SDK](#51-python-sdk)
  - [5.2 Import OpenAI Conversations and Auto-Extract Skills](#52-import-openai-conversations-and-auto-extract-skills)
  - [5.3 Offline Conversation Extraction via CLI](#53-offline-conversation-extraction-via-cli)
  - [5.4 Offline Trajectory Extraction via CLI](#54-offline-trajectory-extraction-via-cli)
- [6. Provider Setup](#6-provider-setup)
  - [6.1 DashScope (Example)](#61-dashscope-example)
  - [6.2 GLM (BigModel)](#62-glm-bigmodel)
  - [6.3 OpenAI / Anthropic](#63-openai--anthropic)
  - [6.4 InternLM (Intern-S1 Pro)](#64-internlm-intern-s1-pro)
  - [6.5 Generic URL-based Backends](#65-generic-url-based-backends)
- [7. Runtime Workflows and APIs](#7-runtime-workflows-and-apis)
  - [7.1 Interactive Chat](#71-interactive-chat)
  - [7.2 Web UI](#72-web-ui)
  - [7.3 Startup Offline Maintenance](#73-startup-offline-maintenance)
  - [7.4 OpenAI-Compatible Proxy API](#74-openai-compatible-proxy-api)
  - [7.5 Auto Evaluation Script](#75-auto-evaluation-script)

## 1. Quick Start

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

Open `http://127.0.0.1:8000`.

### 1.2 Standard API Proxy

AutoSkill can also be deployed as a reverse proxy that exposes OpenAI-compatible endpoints while transparently applying:
- skill retrieval and injection for each chat request
- asynchronous skill extraction and maintenance after responses

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

Endpoints:
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`
- `GET /health`

Streaming chat example:

```bash
curl -N http://127.0.0.1:9000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "intern-s1-pro",
    "stream": true,
    "messages": [
      {"role": "user", "content": "Write a concise summary of skill self-evolution."}
    ]
  }'
```

### 1.3 One-click Deploy (Docker Compose)

```bash
cp .env.example .env
# edit .env and fill API keys
docker compose up --build -d
```

After startup:
- Web UI: `http://127.0.0.1:8000`
- API Proxy: `http://127.0.0.1:9000`

Stop services:

```bash
docker compose down
```

## 2. Core Workflow

### 2.1 Ingest and Evolve

```text
Experience (messages/events)
  -> Skill Extraction (candidate)
  -> Skill Maintenance (add / merge / discard)
  -> Skill Store (Agent Skill artifact + vector index)
```

- Extractor emits at most one high-quality candidate per attempt.
- Maintainer checks similarity against existing skills, then decides add, merge, or discard.
- Merge updates preserve and improve capabilities, then bump patch version.

### 2.2 Retrieve and Respond

```text
User Query (+ recent history)
  -> Query Rewrite (optional)
  -> Embedding + Search
  -> Skill Selection for Context
  -> LLM Response
```

- Retrieval runs every turn.
- Similarity threshold and `top_k` control precision and recall.
- Retrieved skills are filtered again before context injection.
- The top-1 retrieved skill, if it passes `min_score`, is passed to extraction as auxiliary identity context.
- Retrieved skills are audited asynchronously for actual relevance and usage in the final reply.
- Usage counters are isolated per user and can auto-prune stale user skills with defaults `retrieved >= 40` and `used <= 0`.

### 2.3 Interactive Extraction Policy

- `extract_mode=auto`: attempt extraction every `extract_turn_limit` turns.
- `extract_mode=always`: attempt every turn.
- `extract_mode=never`: disable auto extraction.
- `/extract_now [hint]`: force immediate background extraction for current context.
- Generic one-off requests without durable correction should return no skill extraction.
- User feedback that encodes stable preferences or constraints should trigger extraction or update.
- If a similar user skill already exists, prefer merge and update over creating duplicates.

### 2.4 Proxy Serving Flow

```text
Client (OpenAI-compatible request)
  -> AutoSkill Proxy (/v1/chat/completions)
  -> Query rewrite + skill retrieval + context injection
  -> Upstream model generation
  -> Return response to client
  -> Async skill extraction and maintenance
```

- Response latency focuses on retrieval plus generation.
- Skill evolution runs asynchronously to avoid blocking the client.

## 3. SkillBank Storage Layout

When using `store={"provider": "local", "path": "SkillBank"}`:

```text
SkillBank/
  Users/
    <user_id>/
      <skill-slug>/
        SKILL.md
        scripts/          (optional)
        references/       (optional)
        assets/           (optional)
  Common/
    <skill-slug>/SKILL.md
    <library>/<skill-slug>/SKILL.md
  vectors/
    <embedding-signature>.meta.json
    <embedding-signature>.ids.txt
    <embedding-signature>.vecs.f32
  index/
    skills-bm25.*          (persistent BM25 index files)
    skill_usage_stats.json (per-user retrieval and usage counters)
```

Notes:
- `Users/<user_id>`: user-specific skills.
- `Common/`: shared library skills.
- `vectors/`: persistent vector cache keyed by embedding signature.
- `index/`: BM25 index and usage statistics used by retrieval and stale-skill pruning.

## 4. Package Structure

### 4.1 Core SDK Modules

- `client.py`: public SDK entrypoint (`ingest`, `search`, `render_context`, import and export).
- `config.py`: global config model.
- `models.py`: core data models (`Skill`, `SkillHit`, and related types).
- `render.py`: convert selected skills into injectable context.
- `skill_provenance.py`: local skill provenance tracking and version history helpers.
- `llm/`: pluggable LLM backends.
- `embeddings/`: pluggable embedding backends.

### 4.2 Skill Management Layer

- `management/extraction.py`: extraction logic and prompts.
- `management/maintenance.py`: merge, version, and add/discard decisions.
- `management/formats/agent_skill.py`: `SKILL.md` render and parse.
- `management/stores/local.py`: directory-based storage plus vector mapping.
- `management/vectors/flat.py`: on-disk vector index backend.
- `management/importer.py`: import external Agent Skills.

### 4.3 Interactive Layer

- `interactive/app.py`: terminal interactive app orchestration.
- `interactive/session.py`: headless session engine for Web and API usage.
- `interactive/server.py`: OpenAI-compatible reverse proxy runtime.
- `interactive/rewriting.py`: query rewriting for better retrieval.
- `interactive/selection.py`: optional LLM skill selection before injection.
- `interactive/unified.py`: unified composition root for interactive and proxy wiring.

### 4.4 Offline Layer

- `offline/conversation/extract.py`: import OpenAI-format conversation `.json/.jsonl` and extract skills.
- `offline/trajectory/extract.py`: import offline agentic trajectory data and extract workflow skills.
- `offline/document` is no longer part of `autoskill/`; document extraction is maintained in [../AutoSkill4Doc/README.md](../AutoSkill4Doc/README.md).

### 4.5 Example Entrypoints

- `../examples/web_ui.py`: local Web UI server.
- `../examples/interactive_chat.py`: CLI interactive chat.
- `../examples/openai_proxy.py`: OpenAI-compatible proxy entrypoint.
- `../examples/auto_evalution.py`: automated LLM-vs-LLM evolution evaluation.
- `../examples/basic_ingest_search.py`: minimal SDK loop.

## 5. SDK and Offline Usage

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

### 5.2 Import OpenAI Conversations and Auto-Extract Skills

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

Notes:
- Input format should be OpenAI-style conversations (`.json` / `.jsonl` with `messages`).
- Offline extraction structures the payload into:
  - `Primary User Questions (main evidence)`
  - `Full Conversation (context reference)`
- User turns are primary evidence; assistant-side artifacts are excluded from skill evidence.

### 5.3 Offline Conversation Extraction via CLI

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./data/random_50 \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope
```

Behavior:
- `--file` accepts one OpenAI-format `.json`/`.jsonl` file or a directory containing multiple files.
- If a single `.json` file contains multiple conversations, the loader iterates all conversation units.
- The runner prints per-file progress in real time, including file name and extracted skill names.

### 5.4 Offline Trajectory Extraction via CLI

```bash
python3 -m autoskill.offline.trajectory.extract \
  --file ./data/traces \
  --user-id u1 \
  --llm-provider dashscope \
  --embeddings-provider dashscope \
  --success-only 1 \
  --include-tool-events 1
```

## 6. Provider Setup

### 6.1 DashScope (Example)

```bash
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.interactive_chat --llm-provider dashscope
```

### 6.2 GLM (BigModel)

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

### 6.4 InternLM (Intern-S1 Pro)

```bash
export INTERNLM_API_KEY="YOUR_INTERNLM_TOKEN"
python3 -m examples.interactive_chat --llm-provider internlm --llm-model intern-s1-pro
```

### 6.5 Generic URL-based Backends

```bash
export AUTOSKILL_GENERIC_LLM_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_LLM_MODEL="gpt-5.2"
export AUTOSKILL_GENERIC_EMBED_URL="http://XXX/v1"
export AUTOSKILL_GENERIC_EMBED_MODEL="embd_qwen3vl8b"
export AUTOSKILL_GENERIC_API_KEY=""

python3 -m examples.interactive_chat --llm-provider generic --embeddings-provider generic
```

## 7. Runtime Workflows and APIs

### 7.1 Interactive Chat

```bash
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.interactive_chat --llm-provider dashscope
```

Useful commands:
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

### 7.3 Startup Offline Maintenance

When service runtime starts (`web_ui`, `interactive_chat`, `openai_proxy`), AutoSkill can automatically:
- normalize missing `id:` in `SKILL.md`
- optionally import external skill directories when `AUTOSKILL_AUTO_IMPORT_DIRS` is configured

Optional environment controls:
- `AUTOSKILL_AUTO_NORMALIZE_IDS`
- `AUTOSKILL_AUTO_IMPORT_DIRS`
- `AUTOSKILL_AUTO_IMPORT_SCOPE`
- `AUTOSKILL_AUTO_IMPORT_LIBRARY`
- `AUTOSKILL_AUTO_IMPORT_OVERWRITE`
- `AUTOSKILL_AUTO_IMPORT_INCLUDE_FILES`
- `AUTOSKILL_AUTO_IMPORT_MAX_DEPTH`

### 7.4 OpenAI-Compatible Proxy API

```bash
export INTERNLM_API_KEY="YOUR_INTERNLM_API_KEY"
export DASHSCOPE_API_KEY="YOUR_DASHSCOPE_API_KEY"
python3 -m examples.openai_proxy --llm-provider internlm --embeddings-provider qwen
```

Discoverability:

```bash
curl http://127.0.0.1:9000/v1/autoskill/capabilities
curl http://127.0.0.1:9000/v1/autoskill/openapi.json
```

OpenAI-compatible endpoints:
- `POST /v1/chat/completions`
- `POST /v1/embeddings`
- `GET /v1/models`

Skill APIs:
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

Retrieval and extraction:
- `POST /v1/autoskill/retrieval/preview`
- `POST /v1/autoskill/extractions`
- `POST /v1/autoskill/extractions/simulate`
- `GET /v1/autoskill/extractions/latest`
- `GET /v1/autoskill/extractions`
- `GET /v1/autoskill/extractions/{job_id}`
- `GET /v1/autoskill/extractions/{job_id}/events`

### 7.5 Auto Evaluation Script

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
