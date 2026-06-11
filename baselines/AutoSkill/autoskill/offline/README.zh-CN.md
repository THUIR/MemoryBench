# AutoSkill Offline

[English](README.md) | 中文

`autoskill.offline` 提供面向历史数据的离线技能抽取能力。当前这个 README 主要说明 `conversation` pipeline：

- `conversation`：历史 OpenAI 格式对话 -> 可复用的用户技能

## Conversation Pipeline

`conversation` 主要关注用户自己提出的可复用要求。它会把每段对话整理成统一抽取输入，其中：

- `Primary User Questions` 作为主要证据
- `Full Conversation` 只作为辅助上下文

assistant 的回复只用于参考，不直接作为技能要求写入。该 pipeline 还会为每个用户维护离线需求记忆，用于支持：

- 原子化需求抽取
- 需求标准化
- 同一技能谱系内的同需求匹配
- 多次更新中的提及次数统计
- 低频一次性约束的保留/删除决策

需求统计文件默认保存在：

```text
<store_root>/index/offline_requirement_stats_<user_id>.json
```

## 输入要求

Conversation 输入：

- 单个 `.json` 或 `.jsonl` 文件，内容为 OpenAI 风格消息格式
- 或包含这类文件的目录
- 单个 JSON 文件中可以是一段对话，也可以包含多段对话

## 配置方式

Conversation pipeline 在未显式传参时，会读取以下环境变量：

```bash
export AUTOSKILL_LLM_PROVIDER=internlm
export AUTOSKILL_LLM_MODEL=intern-s1
export AUTOSKILL_LLM_API_KEY=...

export AUTOSKILL_EMBEDDINGS_PROVIDER=qwen
export AUTOSKILL_EMBEDDINGS_MODEL=text-embedding-v4
export AUTOSKILL_EMBEDDINGS_API_KEY=...

export AUTOSKILL_STORE_PATH=./SkillBank
```

常用可选参数：

- `--user-id`：用户命名空间
- `--hint`：额外抽取提示
- `--max-workers`：并发抽取 worker 数，默认 `50`，`0` 表示自动
- `--store-path`：覆盖本地 SkillBank 路径

## CLI 用法

Conversation：

```bash
python3 -m autoskill.offline.conversation.extract \
  --file ./conversation_logs \
  --user-id u1 \
  --max-workers 8 \
  --max-messages-per-conversation 0
```

Conversation，显式指定模型：

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

## 输出内容

Conversation CLI 会输出：

- 每段对话的处理进度
- 抽取出的技能名称
- 汇总统计：`conversations / processed / failed / upserted`
- requirement stats 的保存路径

并发说明：

- 候选技能抽取阶段会并发执行
- merge / 版本更新 / 本地落库阶段仍按输入顺序串行执行
- 这样可以避免多个对话同时更新同一技能谱系时出现竞争问题

返回的技能摘要中常见字段包括：

- `id`
- `name`
- `description`
- `version`
- `triggers`
- `tags`
- `examples`

## 包结构

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
