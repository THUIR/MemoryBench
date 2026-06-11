# AutoSkill4Doc

[English](README.md) | 中文

`AutoSkill4Doc` 是仓库内独立的离线文档抽取与技能编译引擎。
它通过明确的离线阶段把文档转换为可执行技能，并保留来源追踪、
版本历史与可增量重跑能力。

## 范围

当前主流程：

```text
document
  -> ingest_document（DocumentRecord + TextUnit + StrictWindow）
  -> extract_skills（SupportRecord + SkillDraft）
  -> compile_skills（SkillSpec）
  -> register_versions
  -> registry + staging 快照 + 最终 SkillBank store + 可见领域/family/层级技能树
```

核心分层：

1. `DocumentRecord`
2. `TextUnit`
3. `StrictWindow`
4. `SupportRecord`
5. `SkillDraft`
6. `SkillSpec`

## 核心能力

- 独立 CLI：`autoskill4doc ...` 或 `python -m AutoSkill4Doc ...`
- 基于 `content_hash` 的增量跳过
- section 过滤、strict/recommended 窗口切分
- 支持 `--extract-workers` 的文档级并行抽取；同一篇文档内部仍按原顺序逐个 window 抽取，最终结果按输入文档顺序归并
- 非 `--quiet` CLI 运行时，会显示单行实时的多阶段进度：抽取阶段展示文档和 window 进度，后续阶段展示 compile 分组和 register 技能进度
- 抽取阶段遇到限流、短时过载或瞬时网络错误时会做指数退避重试，而不是直接丢掉文档；可用 `--extract-retries` 和 `--extract-retry-backoff-s` 调整
- AutoSkill4Doc 现在默认带一层共享的自适应背压：outline 分类、family 判定、抽取、compile、versioning 任何阶段遇到 429/超时/过载/SSL 一类瞬时错误，后续请求都会自动冷却退让，而不是继续立刻打同一个 provider
- 还支持通过 `--llm-rate-limit-requests` 和 `--llm-rate-limit-window-s` 做主动限流；多 worker 运行时会在共享配额下排队，而不是直接把 provider 打到 `429`
- 如果某篇文档在重试后仍失败，AutoSkill4Doc 会按文档记录失败并继续处理整批其它文档，而不是整批直接中断
- 抽取现在采用两阶段 window 流程：先判断当前 window 实际包含几个独立 skill，再逐个展开详细抽取，避免多个 skill 共用一次响应预算导致后面的 skill 变薄
- 默认会对每篇文档的候选标题做一次紧凑的 outline 级 LLM 结构分类来判断 section / subsection 层级；规则负责召回候选与兜底。只有显式指定 `section-outline-mode=rule` 时才完全走规则
- 支持 dry-run 和分阶段执行
- 支持 provenance/change log/version history
- 支持生命周期状态：`candidate -> draft -> evaluating -> active -> watchlist -> deprecated -> retired`
- 支持在文档技能库根目录下生成 `领域总技能 / Family技能 / 一级技能 / 二级技能 / 微技能 / references` 可见树
- 非 `dry-run` 构建过程中会把中间结果写到 `.runtime/intermediate_runs/<run_id>/`
- 检索使用的文本、向量和 BM25 token index 会落盘到 `.runtime/store/document_skill_retrieval.json`
- 支持通过内置或自定义 YAML 配置技能 taxonomy，`domain_type` 由调用方显式提供，不由模型预测

输入说明：
- `text / markdown / json / jsonl` 可直接读取
- `.doc / .docx` 依赖本地转换工具，例如 `textutil`、`antiword`、`catdoc`
- 图片、PDF 等当前不支持直接解析，会被跳过而不是作为乱码文本导入
- `generic` LLM / embedding 后端需要显式设置 `AUTOSKILL_GENERIC_LLM_URL` / `AUTOSKILL_GENERIC_EMBED_URL`
- 已导出的可见技能树产物（`总技能/`、`一级技能/`、`二级技能/`、`微技能/`、`Family技能/`、`references/`）在 ingest 时会被自动跳过，避免把生成后的技能再次当作原始文档抽取

## 默认路径

默认库目录：

```text
<repo_root>/SkillBank/DocSkill/
```

默认 registry 路径：

```text
<store_root>/.runtime/document_registry/
```

默认中间结果路径：

```text
<store_root>/.runtime/intermediate_runs/
```

可见输出结构：

```text
<store_root>/
  README.md
  <domain_root>/
    总技能/
      SKILL.md
      references/
        domain_manifest.json
    Family技能/
      <family_name>/
        总技能/
          SKILL.md
          references/
            children_manifest.json
            children_map.md
        一级技能/
          <skill_name>/
            SKILL.md
            references/
              children_manifest.json
              children_map.md
              evidence.md
              evidence_manifest.json
        二级技能/
          <skill_name>/
            SKILL.md
            references/
              children_manifest.json
              children_map.md
              evidence.md
              evidence_manifest.json
        微技能/
          <skill_name>/
            SKILL.md
            references/
              evidence.md
              evidence_manifest.json
  Users/
    docskill/
      ...
  .runtime/
    document_registry/
    intermediate_runs/
    store/
      document_skill_retrieval.json
    staging/
    library_manifest.json
```

同一个库根目录下现在有 3 层存储：

1. `.runtime/document_registry/`
   - 内部 document / support / skill / version 记录
2. `Users/<internal_user>/`
   - 由已协调后的 `SkillSpec` 直接同步得到的最终 AutoSkill 本地 store 技能
3. `<domain_root>/`
   - 面向浏览和导出的领域根、family 根以及 `一级技能 / 二级技能 / 微技能` 投影

它们共用同一个根目录，但不是同一份数据。对于长任务，非 `dry-run`
构建还会把阶段快照持续写到 `.runtime/intermediate_runs/<run_id>/`。如果任务在
ingest / extract / compile / register 之后中断，重新用相同输入和配置启动时，
会自动复用最近一次未完成 run 的阶段快照继续执行，而不是从头再抽取一遍。
单篇文档的抽取失败也会落到 `extract/documents/<doc_id>.json`，因此长任务可以以
“部分成功 + 明确失败文档清单”的形式结束，而不是只能全成或全挂。

## 总技能 / 子技能是如何生成的

当前实现不是直接从文档一次性吐出一个“总技能目录树”，而是分两层：

1. 先把文档抽成 `SkillSpec`
   - `ingest` 负责把文档切成 `StrictWindow`
     - 支持 markdown 标题以及 `3`、`3.1`、`第3章`、`（一）` 这类编号章节
     - window 规划时会先按根章节分组，因此像 `4.1 / 4.2 / 5.1` 这样的子章节会归到 `4 ...` / `5 ...` 这类大章节下面，而不是被当成独立顶层切片单位
     - 每个 window 都会附带 `heading_path`、`parent_heading`、`sibling_headings`、`subsection_headings` 等层级上下文
     - 规则先召回可能为标题的行；如果提供了 LLM，AutoSkill4Doc 会对这些候选做一次紧凑的 outline LLM 分类，用来判断章节和子章节层级
     - 超长章节会先预切片，再进入最终 window 规划；默认 `--max-section-chars` 为 `10000`
     - 参考文献 / bibliography 类章节会在抽取前被跳过
   - `extract` 会先判断一个 window 里有几个独立 skill，再逐个展开成 `SupportRecord + SkillDraft`
   - `compile` 负责把 draft 归一成 `SkillSpec`
   - `register_versions` 会先用带 metadata 的技能文本做 embedding + BM25 hybrid 检索，召回 top-k 相似旧技能，再判断 create / strengthen / revise / merge / split / unchanged，最后做 registry 持久化和版本状态处理
   - 检索语料文本、向量和 BM25 token index 会持久化到 `.runtime/store/document_skill_retrieval.json`，下次运行优先复用

2. 再把结果投影成可见 domain/family 树
   - 如果最终 store skill 已存在，可见 family 技能会优先按 `Users/<internal_user>/...` 里的最终技能重建
   - 证据文件：`references/evidence.md` 和 `references/evidence_manifest.json` 仍由 registry 中关联的 `SupportRecord + DocumentRecord` 拼接
   - 领域根：每个 `domain_root` 会合成一个领域总技能
   - family 根：每个 `family_name` 会合成一个 family 总技能
   - 一级/二级父技能：当存在已链接的子技能时，会在自身目录下生成嵌套 `children_manifest.json` 和 `children_map.md`

这种实现的好处是：

- 原始真相仍然保留在 registry 的 document / support / skill 层，不是只有一个最终 `SKILL.md`
- 领域根和 family 根技能只是导航层，不会反过来污染原始 skill 事实
- 子技能更新后，可以整体重建同一家族的可见树，避免目录漂移
- 现在可见树会优先对齐最终 store skill，因此会尽量和 `Users/<internal_user>/...` 保持一致
- 嵌套父技能可以附带子技能目录和选用规则，但底层 registry 真相层不变

当前要稳定得到你想要的目录结构，最重要的是构建时显式传：

- `--family-name`

其中 `--family-name` 最关键，因为它直接决定 `<domain_root>/Family技能/` 下面的 family 子树名称。
如果不传 `--profile-id`，系统会基于 taxonomy 和 `family_name` 自动派生；
如果不传 `--taxonomy-axis`，则会优先使用 taxonomy 配置里的默认值。
如果不传 `--family-name`，AutoSkill4Doc 会先尝试 taxonomy 规则命中，再对 `family_candidates` 做一次受约束的 LLM 分类。
`--user-id` 现在只是内部 store 路由细节，不再是正常文档抽取流程里需要关心的主参数。
如果省略，AutoSkill4Doc 会使用更中性的内部用户 id：`docskill`。

## Skill Taxonomy

`AutoSkill4Doc` 内部仍然保持一组稳定的 `asset_type`，供 compile / versioning 使用：

- `macro_protocol`
- `session_skill`
- `micro_skill`
- `safety_rule`
- `knowledge_reference`

在这层之上，可以通过 taxonomy 配置给出领域自己的标签、别名和层级节点树：

- 内置 taxonomy：`--domain-type psychology` / `--domain-type chemistry`
- 自定义 taxonomy：`--skill-taxonomy /path/to/taxonomy.yaml`

注意：

- `domain_type` 是用户或调用方已知的配置输入，不是模型预测结果
- 模型最终仍返回内部稳定的 `asset_type`
- taxonomy 文件除了提供领域标签、别名和提示词引导，还可以同时提供：
  - 默认 `family_name`
  - 默认 `taxonomy_axis`
  - family 候选集合（供后续受约束的 family 判定使用）
  - `asset_tree`：层级节点树，例如 `总技能 -> 一级技能 -> 二级技能 -> 微技能`
  - `visible_levels`：不同层级在可见目录中的默认标签

示例：

```bash
python3 -m AutoSkill4Doc llm-extract \
  --file ./chem_docs \
  --domain chemistry \
  --domain-type chemistry \
  --family-name "分析化学" \
  --skill-taxonomy ./custom-taxonomy.yaml \
  --store-path ./SkillBank/DocSkill
```

## 配置文件说明

当前 `AutoSkill4Doc` 的配置主要来自 3 层：

1. 内置 taxonomy 文件
   - [AutoSkill4Doc/skill_taxonomies/default.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/default.yaml)
   - [AutoSkill4Doc/skill_taxonomies/psychology.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/psychology.yaml)
   - [AutoSkill4Doc/skill_taxonomies/chemistry.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/chemistry.yaml)
2. 用户通过 `--skill-taxonomy` 传入的自定义 taxonomy 文件
3. 运行时 CLI 参数与 provider 环境变量

taxonomy 的加载顺序是：

- 总是先加载 `default.yaml`
- 如果传了 `--domain-type psychology` / `chemistry`，再把对应内置 taxonomy 叠加到 `default.yaml` 上
- 如果传了 `--skill-taxonomy /path/to/file.yaml`，则用这个自定义文件作为 overlay，替代内置 domain 文件
- 最终解析后的结果会用于：
  - 抽取 prompt 的领域提示
  - `asset_type` 别名归一化
  - `asset_node_id` 层级节点归一化
  - 默认 `family_name`
  - 默认 `taxonomy_axis`
  - 自动派生 `profile_id`

taxonomy 里几个最重要的字段：

- `taxonomy_id`：稳定 taxonomy 标识，用于派生 `profile_id`
- `domain_type`：调用方显式指定的领域类型名
- `display_name`：展示名称
- `default_base_type`：默认内部 `asset_type`
- `family_axis`：默认可见分类轴，例如 `疗法`、`实验路线`
- `default_family_name`：默认 family 名称
- `family_candidates`：可选 family 候选集合，供后续受约束判定使用
- `asset_types`：领域标签到内部稳定 base type 的映射
- `visible_levels`：`总技能 / 一级技能 / 二级技能 / 微技能` 这类可见层标签
- `asset_tree`：配置驱动的层级技能节点树；模型可返回 `asset_node_id`，系统据此约束同级合并与后续父子链接

`asset_types` 和 `asset_tree` 是两层不同概念：
- `asset_types` 负责稳定粗类型，例如 `session_skill`、`micro_skill`
- `asset_tree` 负责可见层级和父子结构，例如 `family_root -> 一级技能 -> 二级技能 -> 微技能`

最小 taxonomy 示例：

```yaml
taxonomy_id: psychology
domain_type: psychology
display_name: Psychology
default_base_type: session_skill
family_axis: 疗法
default_family_name: 通用心理咨询
family_candidates:
  - id: cbt
    name: CBT（认知行为疗法）
    aliases: ["CBT", "认知行为疗法", "cognitive behavioral therapy"]
visible_levels:
  root_label: 总技能
  level_labels:
    "1": 一级技能
    "2": 二级技能
    "3": 微技能
asset_types:
  - base_type: session_skill
    label: session_intervention
    description: One counseling workflow or session scaffold.
    aliases: ["session_intervention", "session_skill"]
asset_tree:
  - id: session_framework
    label_zh: 二级技能
    label_en: Second-Level Skill
    base_type: session_skill
    level: 2
    parent: treatment_framework
    visible_role: parent
    default_for_base_type: true
```

其他配置入口：

- [AutoSkill4Doc/core/config.py](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/core/config.py)
  - 代码默认值，例如默认 store 路径、runtime 路径、extract strategy、章节预切片大小、章节 outline fallback 模式
- [AutoSkill4Doc/core/provider_config.py](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/core/provider_config.py)
  - `dashscope`、`glm`、`openai`、`anthropic`、`generic` 的 provider/env 解析

provider 配置不是文件，而是环境变量。常用项包括：

- DashScope：`DASHSCOPE_API_KEY`，可选 `DASHSCOPE_MODEL`、`DASHSCOPE_EMBED_MODEL`
- GLM：`ZHIPUAI_API_KEY` 或 `BIGMODEL_API_KEY`
- Generic backend：`AUTOSKILL_GENERIC_LLM_URL`、`AUTOSKILL_GENERIC_EMBED_URL`

补充说明：

- 用户侧抽取命令（`build`、`llm-extract`、`extract`、`compile`、`diag`）现在不会再静默回退到 `mock`
- 如果当前环境里解析不到真实 provider，AutoSkill4Doc 会直接报错，而不是进入仅供测试使用的 mock 行为
- `mock` 只保留给开发/测试路径

解析优先级：

- 显式 CLI 参数
- 自定义 taxonomy 文件
- 内置 taxonomy 文件
- `core/config.py` 中的代码默认值
- provider 的环境变量（用于认证和 endpoint URL）

切片 / 层级识别相关参数：

- `--max-section-chars`
  - 一个检测到的章节如果过长，会先按这个上限预切片，再构造最终 extraction windows
  - 默认：`10000`
- `--section-outline-mode llm|rule`
  - `llm`：默认；对每篇文档的候选标题做一次紧凑的 outline LLM 层级分类；规则只负责召回候选和兜底
  - `rule`：完全关闭这层 outline LLM 分类，只使用规则判断
  - 兼容别名：`auto -> llm`，`off -> rule`
- `--llm-rate-limit-requests` + `--llm-rate-limit-window-s`
  - 对 outline 分类、family 判定、抽取、compile、versioning 共用一套 rolling-window 请求配额
  - 即使不显式设置这两个参数，遇到 provider 瞬时错误时也会自动触发共享冷却退让
  - 适合 provider 给出类似 `5 分钟最多 2000 次` 的限制
  - 示例：`--llm-rate-limit-requests 2000 --llm-rate-limit-window-s 300`

## 流程是否合理

按当前版本来看，这个流程作为最小可运行版本是合理的：

- 抽取主链路和可见目录生成解耦
- `领域总技能 / Family技能 / 分层技能` 是落盘投影，不是新的“真相层”
- 重新同步目录时以最终 store 结果为主、以 registry 证据为辅，能避免人工目录漂移

但它和 paper 目标相比，仍然是一个简化版：

- 现在的领域根和 family 根技能是基于当前有效子技能自动汇总出来的
- 还没有完整实现 paper 里的 `single-document standardization + canonical merge + parent synthesis` 全链路
- 所以目录结构已经对齐了，但“子技能如何合并成 canonical child”的治理强度还没完全到 paper 那个版本
- `.runtime/document_registry/` 里当前仍可能保留比最终 `Users/<internal_user>/...` 和 `<domain_root>/Family技能/<family_name>/...` 更多的内部 skill 记录

如果你的当前优先级是“先保证输出长得对”，这版已经够用。  
如果你的优先级是“保证和 paper 一样的归并质量”，下一步要继续补 canonical merge 那一段。

落盘对象：

- `documents`
- `supports`
- `skills`
- `lifecycles`
- `version_history`
- `change_logs`
- `provenance_links`

## CLI

独立 CLI：

```bash
python3 -m AutoSkill4Doc build --file ./paper.md --dry-run
python3 -m AutoSkill4Doc llm-extract --file ./cbt_docs --family-name "认知行为疗法"
python3 -m AutoSkill4Doc ingest --file ./docs/ --json
python3 -m AutoSkill4Doc extract --file ./paper.md --json
autoskill4doc compile --file ./paper.md --json
python3 -m AutoSkill4Doc diag --file ./paper.md --report-path ./diag.jsonl --json
python3 -m AutoSkill4Doc retrieve-hierarchy --store-path ./SkillBank/DocSkill --profile-id psychology::认知行为疗法 --family-name "认知行为疗法" --json
python3 -m AutoSkill4Doc canonical-merge --store-path ./SkillBank/DocSkill --family-name "认知行为疗法" --json
python3 -m AutoSkill4Doc migrate-layout --store-path ./SkillBank/DocSkill --json

python3 -m AutoSkill4Doc build \
  --file ./cbt_docs/ \
  --domain psychology \
  --domain-type psychology \
  --family-name "认知行为疗法" \
  --store-path ./SkillBank/DocSkill
```

说明：
- `dry-run` 会跑 ingest/extract/compile 供你查看结果，但不会写入最终 registry / skill store / 可见技能树。
- `diag` 始终以 dry-run 观察模式运行，不会写入 registry 或 skill store。
- 非 `dry-run` 的 `build / llm-extract` 会把 ingest / extract / compile / register 的阶段快照写到 `.runtime/intermediate_runs/<run_id>/`。
- 同一个非 `dry-run` 构建还会把检索文本、embedding 向量和 BM25 token index 写到 `.runtime/store/document_skill_retrieval.json`。
- 重新运行相同的非 `dry-run` 输入/配置时，会自动恢复最近一次未完成的 intermediate run；已经完成抽取的文档不会再次抽取。
- 如果库里当前只存在一个可见 family，`retrieve-hierarchy` 会直接打开这棵 family 树，而不是先返回只有一项的 family 列表。
- `canonical-merge` 当前用于查看 staging 结果。如果 staging 中只有一个唯一 bucket，会自动推导 `profile_id`、`family_name` 和 `child_type`；否则再显式传入。
- 如果不传 `--family-name`，系统会先用 taxonomy 里的别名/关键词做规则判定，再做一次受约束的 LLM family 分类；如果证据仍然偏弱，就回退到 taxonomy 的 `default_family_name`，而不是候选列表中的第一个 family。
- 如果同一批文档明显命中多个不同的 configured family，批次级 family 会回退到 taxonomy 默认 family；同时，文档级 family 元数据仍会保留在抽取出的 skill 上，后续 versioning 和可见树投影仍可继续利用这些更细的 family 线索。

## Python API

```python
from AutoSkill4Doc import extract_from_doc

result = extract_from_doc(
    sdk=sdk,
    file_path="./paper.md",
    domain="psychology",
    domain_type="psychology",
    family_name="认知行为疗法",
    dry_run=True,
)
```

分阶段调用：

```python
from AutoSkill4Doc.pipeline import build_default_document_pipeline

pipeline = build_default_document_pipeline(sdk=sdk)
ingest = pipeline.ingest_document(file_path="./paper.md", dry_run=True)
print(len(ingest.windows))
extracted = pipeline.extract_skills(documents=ingest.documents, windows=ingest.windows)
compiled = pipeline.compile_skills(
    skill_drafts=extracted.skill_drafts,
    support_records=extracted.support_records,
)
```

## 模块结构

- `extract.py` / `__main__.py`：独立包 CLI + API 入口
- `pipeline.py`：分阶段编排
- `ingest.py`：文档归一化与增量检测
- `taxonomy.py`：内置/自定义 skill taxonomy 加载，以及 domain/family/层级配置解析
- `family_resolver.py`：基于 `family_candidates` 的受约束 family 判定
- `document/file_loader.py`：目录/文件读取、转换兜底与生成产物跳过
- `document/windowing.py`：section 过滤与 strict/recommended 窗口构造
- `stages/extractor.py`：`DocumentRecord -> SupportRecord[] + SkillDraft[]`
- `stages/compiler.py`：`SkillDraft[] -> SkillSpec[]`
- `stages/diag.py`：基于现有抽取链路的 dry-run 诊断报告
- `stages/hierarchy.py`：manifest 优先的可见层级浏览/检索
- `stages/merge.py`：基于 staging 的 canonical merge 结果查看
- `stages/migrate.py`：安全的 `.runtime` 布局准备与迁移检查
- `store/versioning.py`：基于 skill identity 的版本与生命周期治理
- `store/registry.py`：文件系统 registry 持久化
- `store/visible_tree.py`：基于最终 store skill 与 registry 证据导出的可见 `领域总技能 / Family技能 / 一级技能 / 二级技能 / 微技能 / references`
- `store/intermediate.py`：按运行批次持续写入 ingest/extract/compile/register 中间快照
- `store/layout.py`：共享的 visible/runtime 路径约定
- `store/staging.py`：canonical merge staging 读写辅助
- `core/config.py`：AutoSkill4Doc 独立默认路径与配置
- `core/provider_config.py`：独立 provider 配置辅助
- `models.py`：核心数据模型
- `prompts.py`：offline prompt 构造与运行时 prompt 替换

## 迁移说明

- 已替代旧目录 `autoskill/offline/document/`。
- 文档抽取现在直接通过 `AutoSkill4Doc` 运行，不再通过 `autoskill/offline` 路由。
- 推荐入口是 `python -m AutoSkill4Doc`；`extract.py` 作为该 CLI 的实现模块保留。
