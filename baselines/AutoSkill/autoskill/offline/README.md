# AutoSkill Offline

English | [中文](README.zh-CN.md)

`autoskill.offline` provides batch extraction workflows for archived data. This README focuses on the `conversation` pipeline:

- `conversation`: archived OpenAI-format conversations -> reusable user skills

## Conversation Pipeline

`conversation` focuses on user-stated reusable requirements. It converts each conversation into a normalized extraction message with:

- `Primary User Questions` as the main evidence
- `Full Conversation` as secondary context only

Assistant replies are reference-only and should not become skill requirements. The pipeline also maintains offline requirement memory per user:

- atomic requirement extraction
- requirement canonicalization
- same-requirement matching inside one skill lineage
- mention counting across updates
- keep/drop decisions for low-frequency one-off constraints

Requirement stats are stored locally under:

```text
<store_root>/index/offline_requirement_stats_<user_id>.json
```

## Input Expectations

Conversation input:

- a single `.json` or `.jsonl` file in OpenAI-style message format
- or a directory containing such files
- a single JSON file may contain one conversation or multiple conversations

## Configuration

The conversation pipeline reads the following environment variables when flags are omitted:

```bash
export AUTOSKILL_LLM_PROVIDER=internlm
export AUTOSKILL_LLM_MODEL=intern-s1
export AUTOSKILL_LLM_API_KEY=...

export AUTOSKILL_EMBEDDINGS_PROVIDER=qwen
export AUTOSKILL_EMBEDDINGS_MODEL=text-embedding-v4
export AUTOSKILL_EMBEDDINGS_API_KEY=...

export AUTOSKILL_STORE_PATH=./SkillBank
```

Common optional flags:

- `--user-id`: target user namespace
- `--hint`: extra extraction hint
- `--max-workers`: parallel extraction workers, default `50`, `0` means auto
- `--store-path`: override local SkillBank path

## CLI Usage

Conversation:

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./conversation_logs \
  --user-id u1 \
  --max-workers 8 \
  --max-messages-per-conversation 0
```

Conversation with explicit providers:

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./conversation_logs \
  --user-id u1 \
  --llm-provider internlm \
  --llm-model intern-s1 \
  --embeddings-provider qwen \
  --embeddings-model text-embedding-v4 \
  --store-path ./SkillBank
```

## Outputs

Conversation CLI prints:

- per-conversation progress
- extracted skill names
- aggregated counts: `conversations / processed / failed / upserted`
- requirement stats summary path

Concurrency note:

- candidate extraction runs in parallel across conversations
- merge / version update / local persistence still run serially in input order
- this avoids race conditions when multiple conversations update the same skill lineage

The returned skill summaries contain fields such as:

- `id`
- `name`
- `description`
- `version`
- `triggers`
- `tags`
- `examples`

## Package Layout

```text
autoskill/offline/
  __init__.py
  provider_config.py
  README.md
  README.zh-CN.md
  conversation/
    extract.py
    file_loader.py
    prompt_runtime.py
    prompts.py
    requirement_memory.py
```
