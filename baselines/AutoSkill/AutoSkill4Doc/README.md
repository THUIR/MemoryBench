# AutoSkill4Doc

English | [中文](README.zh-CN.md)

`AutoSkill4Doc` is the standalone offline document-to-skill engine for this repository.
It turns documents into executable skills through explicit offline stages, while
keeping provenance, version history, and incremental re-run support.

## Scope

Current pipeline:

```text
document
  -> ingest_document (DocumentRecord + TextUnit + StrictWindow)
  -> extract_skills (SupportRecord + SkillDraft)
  -> compile_skills (SkillSpec)
  -> register_versions
  -> registry + staged snapshots + final SkillBank store + visible domain/family/level skill tree
```

Core layers:

1. `DocumentRecord`
2. `TextUnit`
3. `StrictWindow`
4. `SupportRecord`
5. `SkillDraft`
6. `SkillSpec`

## Key Features

- standalone CLI: `autoskill4doc ...` or `python -m AutoSkill4Doc ...`
- incremental skip by content hash
- section filtering + strict/recommended windowing
- document-level parallel extraction via `--extract-workers`, while each document still extracts windows sequentially and final outputs keep input document order
- in non-`--quiet` CLI runs, the CLI now shows one live single-line multi-stage progress view: extraction reports document and window progress, while later stages report compile-group and register-skill progress
- transient extraction failures such as rate limits or short-lived overload now retry with exponential backoff instead of dropping the document immediately; tune with `--extract-retries` and `--extract-retry-backoff-s`
- AutoSkill4Doc now applies shared adaptive backpressure by default across outline classification, family resolution, extraction, compile, and versioning: transient 429/timeout/overload/SSL-style failures make later requests cool down automatically instead of immediately hammering the same provider again
- optional proactive rolling-window throttling is available via `--llm-rate-limit-requests` and `--llm-rate-limit-window-s`, so multi-worker runs can queue under known provider quotas instead of hammering into 429s
- if one document still fails after retries, AutoSkill4Doc records that failure at the document level and continues the rest of the batch instead of aborting the whole extraction run
- extraction now uses a two-stage window flow: first plan how many distinct skills the window really contains, then expand each planned skill one-by-one so multi-skill windows do not force several full skills to share one response budget
- by default, AutoSkill4Doc uses one compact outline-level LLM classification pass per document over rule-recalled heading candidates to assign section/subsection levels; use `section-outline-mode=rule` only when you explicitly want rules only
- dry-run and stage-by-stage execution
- support-backed provenance and change logs
- lifecycle-aware versioning: `candidate -> draft -> evaluating -> active -> watchlist -> deprecated -> retired`
- visible domain/family/level skill tree under the document skill library root
- incremental intermediate snapshots under `.runtime/intermediate_runs/<run_id>/` during non-dry-run builds
- persisted retrieval cache under `.runtime/store/document_skill_retrieval.json` for retrieval texts, vectors, and BM25 token index
- configurable skill taxonomy via built-in or custom YAML files, with `domain_type` supplied by the caller rather than predicted by the model

Input notes:
- text / markdown / json / jsonl are read directly
- `.doc` / `.docx` require local conversion tools such as `textutil`, `antiword`, or `catdoc`
- unsupported binary files such as images or PDFs are currently skipped rather than decoded as noisy text
- `generic` LLM / embedding backends require explicit `AUTOSKILL_GENERIC_LLM_URL` / `AUTOSKILL_GENERIC_EMBED_URL`
- generated visible-tree artifacts under `总技能/`, `一级技能/`, `二级技能/`, `微技能/`, `Family技能/`, and `references/` are skipped during ingest so exported skills are not re-extracted as source documents

## Default Paths

Default library root:

```text
<repo_root>/SkillBank/DocSkill/
```

Default registry root:

```text
<store_root>/.runtime/document_registry/
```

Default intermediate run root:

```text
<store_root>/.runtime/intermediate_runs/
```

Visible output tree:

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

Storage layers under the same library root:

1. `.runtime/document_registry/`
   - internal document/support/skill/version records
2. `Users/<internal_user>/`
   - final AutoSkill local-store skills synced directly from reconciled `SkillSpec` records
3. `<domain_root>/`
   - visible domain root, family root, and `一级技能 / 二级技能 / 微技能` projection built for browsing and export

These layers share one root, but they are not the same dataset. During long runs,
non-`dry-run` builds also write incremental snapshots under
`.runtime/intermediate_runs/<run_id>/`. If a run crashes after ingest or
extract, rerunning the same input/config automatically reuses the latest
unfinished run and resumes from the persisted stage snapshots instead of
starting extraction from scratch. Per-document extract failures are also
persisted under `extract/documents/<doc_id>.json`, so a long batch can finish
with partial success plus explicit failed-document records instead of failing
all-or-nothing.

## How Parent/Child Skills Are Generated

The current implementation does not try to emit a whole visible skill tree in a
single extraction step. It works in two layers:

1. The document pipeline first produces canonical `SkillSpec` records
   - `ingest` builds `StrictWindow`
     - markdown headings plus numbered / chapter-style headings such as `3`, `3.1`, `第3章`, `（一）`
     - window planning groups subsections under their top-level chapter, so `4.1 / 4.2 / 5.1` style blocks are extracted under `4 ...` / `5 ...` root sections rather than treated as separate top-level units
     - hierarchy metadata (`heading_path`, `parent_heading`, `sibling_headings`, `subsection_headings`) is attached to each window
     - rules first recall candidate heading lines; when an LLM is available, AutoSkill4Doc can do one compact outline LLM pass per document to classify those candidates into section/subsection levels
     - long sections are pre-split before final window planning; default `--max-section-chars` is `10000`
     - bibliography / reference-heavy sections are skipped before extraction
   - `extract` first plans how many skills a window contains and then expands each planned skill individually into `SupportRecord + SkillDraft`
   - `compile` turns drafts into `SkillSpec`
  - `register_versions` retrieves top-k similar existing skills with hybrid embedding + BM25 scoring over metadata-rich skill text, then decides create / strengthen / revise / merge / split / unchanged before persisting registry state and lifecycle updates
  - retrieval texts, corpus vectors, and BM25 tokenized docs are persisted under `.runtime/store/document_skill_retrieval.json` and reused on the next run

2. The visible domain/family tree is then projected for browsing/export
   - if final store skills are available, the visible family skills are rebuilt from the reconciled `Users/<internal_user>/...` store results
   - registry records are still used to stitch `references/evidence.md` and `references/evidence_manifest.json`
   - one domain-root navigation skill is synthesized per `domain_root`
   - one family-root navigation skill is synthesized per `family_name`
   - level-1 / level-2 parent skills can also receive nested `children_manifest.json` and `children_map.md` when linked child skills exist

This is intentional:

- the source of truth stays in document/support/skill registry layers
- the domain/family parent skills remain a navigation layer rather than raw truth
- the visible tree can be rebuilt after updates without manual drift
- the visible family tree now prefers final store-reconciled skills so it stays aligned with `Users/<internal_user>/...`
- nested parent skills can carry child routing sections without changing registry truth

To keep the visible layout stable, the most important flag is:

- `--family-name`

It determines the family subtree under `<domain_root>/Family技能/`.

If `--profile-id` is omitted, AutoSkill4Doc now derives one from the selected
taxonomy plus `family_name`. If `--taxonomy-axis` is omitted, the selected
taxonomy may provide a default axis label. If `--family-name` is omitted,
AutoSkill4Doc first tries taxonomy rule matching and then one constrained LLM
classification pass over the configured `family_candidates`.
`--user-id` is now treated as an internal store-routing detail and is no longer
part of the normal documented workflow. If omitted, AutoSkill4Doc uses the
neutral internal user id `docskill`.

## Skill Taxonomy

`AutoSkill4Doc` keeps a small stable internal `asset_type` set for compile/versioning:

- `macro_protocol`
- `session_skill`
- `micro_skill`
- `safety_rule`
- `knowledge_reference`

On top of that, extraction can load a configurable skill taxonomy:

- built-in via `--domain-type psychology` / `--domain-type chemistry`
- custom via `--skill-taxonomy /path/to/taxonomy.yaml`

Important:

- `domain_type` is caller-provided configuration, not model output
- the model still returns the stable internal `asset_type`
- taxonomy files provide:
  - domain-specific labels, aliases, guidance, and hierarchy nodes
  - optional default `family_name`
  - optional default `taxonomy_axis`
  - optional family candidates for future constrained family resolution
  - optional `asset_tree` and `visible_levels` for multi-level family trees

Example:

```bash
python3 -m AutoSkill4Doc llm-extract \
  --file ./chem_docs \
  --domain chemistry \
  --domain-type chemistry \
  --family-name "分析化学" \
  --skill-taxonomy ./custom-taxonomy.yaml \
  --store-path ./SkillBank/DocSkill
```

## Configuration Files

AutoSkill4Doc currently uses three configuration layers:

1. Built-in taxonomy files
   - [AutoSkill4Doc/skill_taxonomies/default.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/default.yaml)
   - [AutoSkill4Doc/skill_taxonomies/psychology.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/psychology.yaml)
   - [AutoSkill4Doc/skill_taxonomies/chemistry.yaml](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/skill_taxonomies/chemistry.yaml)
2. One optional user taxonomy file passed via `--skill-taxonomy`
3. Runtime CLI arguments and provider env vars

How taxonomy loading works:

- `default.yaml` is always loaded first
- if `--domain-type psychology` / `chemistry` is set, the matching built-in file is overlaid on top of `default.yaml`
- if `--skill-taxonomy /path/to/file.yaml` is set, that file is used as the overlay instead of the built-in domain file
- the final resolved values then feed:
  - extraction prompt guidance
  - `asset_type` alias normalization
  - `asset_node_id` hierarchy-node normalization
  - default `family_name`
  - default `taxonomy_axis`
  - auto-derived `profile_id`

Important taxonomy fields:

- `taxonomy_id`: stable taxonomy id used when deriving `profile_id`
- `domain_type`: the externally supplied domain type name
- `display_name`: human-readable label
- `default_base_type`: fallback internal `asset_type`
- `family_axis`: default visible axis label, such as `疗法` or `实验路线`
- `default_family_name`: fallback visible family name
- `family_candidates`: optional constrained candidate set for future family resolution
- `asset_types`: domain labels mapped back to stable internal base types
- `visible_levels`: visible labels such as `总技能 / 一级技能 / 二级技能 / 微技能`
- `asset_tree`: configuration-driven hierarchy nodes; the model may emit `asset_node_id`, and the pipeline uses it to constrain same-level merge and later parent-child linking

`asset_types` and `asset_tree` are intentionally different layers:
- `asset_types` define stable coarse types such as `session_skill` or `micro_skill`
- `asset_tree` defines the visible hierarchy and parent/child layout such as `family_root -> 一级技能 -> 二级技能 -> 微技能`

Minimal taxonomy example:

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

Other configuration sources:

- [AutoSkill4Doc/core/config.py](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/core/config.py)
  - code defaults such as default store path, runtime path, extract strategy, section pre-split size, and section-outline fallback mode
- [AutoSkill4Doc/core/provider_config.py](/Users/jiezhou/Desktop/工作/其他/浦江/AutoSkill/AutoSkill4Doc/core/provider_config.py)
  - provider/env resolution for `dashscope`, `glm`, `openai`, `anthropic`, and `generic`

Provider config is environment-variable based rather than file-based. Common examples:

- DashScope: `DASHSCOPE_API_KEY`, optional `DASHSCOPE_MODEL`, `DASHSCOPE_EMBED_MODEL`
- GLM: `ZHIPUAI_API_KEY` or `BIGMODEL_API_KEY`
- Generic backend: `AUTOSKILL_GENERIC_LLM_URL`, `AUTOSKILL_GENERIC_EMBED_URL`

Important:

- user-facing extraction commands (`build`, `llm-extract`, `extract`, `compile`, `diag`) no longer silently fall back to `mock`
- if no real provider can be resolved, AutoSkill4Doc exits with an error instead of running with test-only mock behavior
- `mock` remains available only for development/testing paths

Resolution priority:

- explicit CLI argument
- custom taxonomy file
- built-in taxonomy file
- code default in `core/config.py`
- provider env vars for backend credentials and endpoint URLs

Parsing / hierarchy knobs:

- `--max-section-chars`
  - pre-splits one oversized detected section before final window construction
  - default: `10000`
- `--section-outline-mode llm|rule`
  - `llm`: default; do one compact outline LLM classification pass over candidate headings for each document, while rules only recall candidates and provide fallback
  - `rule`: disable outline LLM classification completely and rely on rules only
  - compatibility aliases: `auto -> llm`, `off -> rule`
- `--llm-rate-limit-requests` + `--llm-rate-limit-window-s`
  - enforce one shared rolling-window request budget across outline classification, family resolution, extraction, compile, and versioning
  - even without these flags, AutoSkill4Doc still applies adaptive cooldowns after transient provider failures
  - use this when the provider exposes quotas such as `2000 requests / 300 seconds`
  - example: `--llm-rate-limit-requests 2000 --llm-rate-limit-window-s 300`

## Is The Flow Reasonable

For the current MVP, yes:

- extraction and visible layout generation are decoupled
- parent/child directories are a projection, not the only truth layer
- rebuilding one family directory from final store output plus registry evidence avoids manual drift

But this is still simpler than the full paper target:

- the domain/family parent skills are currently synthesized from active child skills
- the visible tree already matches the target directory shape
- the full `single-document standardization + canonical merge + parent synthesis`
  quality pipeline is not fully implemented yet
- `.runtime/document_registry/` may still contain more internal skill records than
  the final `Users/<internal_user>/...` store and visible `<domain_root>/Family技能/<family_name>/...` tree

Stored entities:

- `documents`
- `supports`
- `skills`
- `lifecycles`
- `version_history`
- `change_logs`
- `provenance_links`

## CLI

Standalone CLI:

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

Notes:
- `dry-run` runs ingest/extract/compile for inspection but does not write final registry/store/visible-tree results.
- `diag` always runs in non-persisting dry-run mode.
- non-`dry-run` `build` / `llm-extract` writes ingest/extract/compile/register snapshots to `.runtime/intermediate_runs/<run_id>/`.
- the same non-`dry-run` build also persists retrieval texts/vectors/BM25 tokens under `.runtime/store/document_skill_retrieval.json`.
- rerunning the same non-`dry-run` build input/config resumes the latest unfinished intermediate run automatically; already extracted documents are not extracted again.
- `retrieve-hierarchy` now opens the family directly when the library contains only one visible family.
- `canonical-merge` currently inspects staged results. When staging contains one unique bucket, it can infer `profile_id`, `family_name`, and `child_type`; otherwise pass them explicitly.
- when `--family-name` is omitted, family resolution first uses configured aliases/keywords, then one constrained LLM classification pass, and finally falls back to the taxonomy's `default_family_name` instead of the first configured candidate.
- when one batch contains documents that strongly match different configured families, the batch-level fallback becomes the taxonomy default family; document-level family metadata is still preserved on extracted skills so later versioning and visible-tree projection can keep specific family signals.

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

Stage-level orchestration:

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

## Module Map

- `extract.py` / `__main__.py`: standalone package CLI + API entrypoint
- `pipeline.py`: staged orchestration
- `ingest.py`: document normalization and incremental checks
- `taxonomy.py`: built-in/custom skill taxonomy loading plus family/domain hierarchy metadata
- `family_resolver.py`: constrained family classification over configured `family_candidates`
- `document/file_loader.py`: directory/file loading, conversion fallback, and generated-artifact skipping
- `document/windowing.py`: section filtering and strict/recommended window construction
- `stages/extractor.py`: `DocumentRecord -> SupportRecord[] + SkillDraft[]`
- `stages/compiler.py`: `SkillDraft[] -> SkillSpec[]`
- `stages/diag.py`: dry-run diagnostic reporting over extraction windows
- `stages/hierarchy.py`: manifest-first visible hierarchy browse/search
- `stages/merge.py`: staging-backed canonical merge inspection
- `stages/migrate.py`: safe runtime layout preparation
- `store/versioning.py`: skill-centric version/lifecycle reconciliation
- `store/registry.py`: filesystem registry persistence
- `store/visible_tree.py`: visible `领域总技能 / Family技能 / 一级技能 / 二级技能 / 微技能 / references` export, rebuilt from final store skills plus registry evidence
- `store/intermediate.py`: incremental per-run ingest/extract/compile/register snapshots
- `store/layout.py`: shared visible/runtime path conventions
- `store/staging.py`: canonical-merge staging payload helpers
- `core/config.py`: standalone AutoSkill4Doc defaults and paths
- `core/provider_config.py`: standalone provider configuration helpers
- `models.py`: core data models
- `prompts.py`: offline prompt builders plus runtime prompt switching

## Notes

- This module replaced the old `autoskill/offline/document/` implementation.
- Document extraction now runs through `AutoSkill4Doc` directly rather than `autoskill/offline`.
- `python -m AutoSkill4Doc` is the recommended module entry; `extract.py` is kept as the implementation module behind that CLI.
