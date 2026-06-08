# Prompt 自进化执行 Workflow

本文档定义当前 offline conversation prompt 自进化的实际执行工作流。

它不是底层技术说明，而是“这一轮应该怎么跑、谁负责什么、每一步要产出什么”的操作规范。

## 1. 核心原则

当前 workflow 采用以下强约束：

1. `data/train` 只用于 evolve
2. `data/eval` 只用于 baseline test 和 final test
   - 两者默认开启，可分别通过 `--eval-before 0` 和 `--eval-after 0` 关闭
3. prompt 不允许自由重写，只允许以 patch 的形式迭代
4. 合成后的 prompt 长度必须位于 `base_prompt` 的长度倍率区间内
   - 默认是 `0.7x ~ 1.5x`
   - 可通过 `--base-prompt-min-length-ratio` 和 `--base-prompt-max-length-ratio` 调整
5. 单轮 candidate prompt 相对当前 active prompt 的变化不超过 `25%`
   - 可通过 `--max-candidate-prompt-change-ratio` 调整
6. 只有 train 上更优且通过 safety gate 的 candidate 才能进入主线
7. reflection 支持两种模式：
   - `codex`
   - `llm`

其中：

- `codex` 模式代表外部反思工作流
- `llm` 模式代表系统内部自动反思工作流

## 2. 角色分工

### 2.1 抽取技能 LLM

职责：

- 按当前 active / candidate prompt 执行 conversation extraction
- 生成 `yes/no`
- 返回 candidate skills

不负责：

- patch 合并
- 主线 promote 决策
- 最终训练/测试指标归档

### 2.2 Reflection backend

当前 reflection 由 [reflection.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/reflection.py) 统一承接，但支持两种执行模式。

#### `codex` 模式

职责：

- 系统只准备 `reflection_input.json`
- 外部由 Codex / 主代理 / 人工审核者分析 `yn / ny`
- 外部写入 `reflection_output.json`
- 再由 `self_evolve/loop.py` 继续 patch merge 和 train eval

补充：

- 如果希望保留 `codex` 的外部反思边界，但又不想每轮手工 `resume`，可以通过 [orchestrator.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/orchestrator.py) 自动接管这个“外部行为”
- orchestrator 会在检测到 pending round 后自动生成 `reflection_output.json`，再继续 `--resume 1`

这种模式适合：

- 不希望把 reflection 交给抽取模型
- 希望避免额外的反思 API 调用
- 希望把反思过程纳入人工审核或代理式流程

#### `llm` 模式

职责：

- 系统自动调用指定的 reflection 模型
- 自动生成 `reflection_output.json`
- 继续 patch merge 和 train eval

这种模式适合：

- 需要全自动闭环
- 可以接受 reflection 由模型完成

### 2.3 主循环

主循环位于：

- [loop.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/loop.py)
- [artifacts.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/artifacts.py)
- [patch.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/patch.py)
- [promotion.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/promotion.py)

职责：

- `loop.py` 负责主流程编排
- `artifacts.py` 负责 run / round 文件管理、legacy 兼容、manifest / history 写入
- `patch.py` 负责 patch normalize、budget merge、candidate prompt 合成、patch artifact 生成
- `promotion.py` 负责 metric 比较、safe gate 与 promote decision
- `eval.py` 负责抽取评测链路与独立 eval CLI
- `reflection.py` 负责 reflection input / output 协议与 LLM reflection

兼容入口：

- [evolve_loop.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/evolve_loop.py)

### 2.4 Codex Auto Orchestrator

自动编排入口位于：

- [orchestrator.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/orchestrator.py)

职责：

- 启动或恢复 `codex` 模式 run
- 识别 `waiting_for_codex_reflection`
- 读取 `reflection_input.json`
- 调用外部 backend 生成 `reflection_output.json`
- 自动继续 `--resume 1` 直到 run 结束

当前支持两种外部 backend：

- `llm`
- `command`

其中：

- `llm` backend 默认复用 reflection LLM 配置，适合先把自动闭环跑通
- `command` backend 适合接入真正的 Codex CLI、主代理脚本或任何自定义外部程序
- 当前默认的 Codex command wrapper 位于 [run_codex_reflection.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/run_codex_reflection.py)
- 这个 wrapper 会直接复用 [reflection.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/reflection.py) 里的 `build_reflection_system_prompt()`，而 `reflection_input.json` 本身仍然来自同一套 `build_reflection_input(...)` 流程
- `command` backend 还支持 `--codex-reflection-max-retries`，默认 `3`，用于在 Codex CLI 临时遇到容量不足或链路波动时自动重试 reflection

## 3. 输入数据

当前 workflow 使用两个数据集。

### 3.1 训练集

- `data/train`
- `data/train/meta_info.jsonl`

用途：

- 生成 `yn / ny`
- 驱动 patch evolve
- 判断 candidate 是否优于当前 active

补充：

- 默认使用 train 全量样本
- 如果启动时传 `--train-max-samples N`，则只使用 `meta_info.jsonl` 的前 `N` 条 train 样本做 baseline train-eval 和后续 round train-eval
- `data/eval` 不受这个参数影响

### 3.2 测试集

- `data/eval`
- `data/eval/meta_info.jsonl`

用途：

- 流程开始前做 baseline test
- 最多 `max-rounds` 轮进化结束后做 final test
- 用于评估泛化能力

禁止事项：

- 不得使用 `data/eval` 的 `yn / ny` 去生成 patch
- 不得用 `data/eval` 指标作为 round promote 的依据

## 4. Run 初始化

每次新实验需要先创建一个 run。

统一输出根目录：

- `log/self-evolve/<stamp>/<run_name>/`

说明：

- 新 run 的所有产物统一写入这一个目录
- 不再拆分为 prompt 根目录和 log 根目录
- 为了兼容历史 run，`--resume 1` 仍可读取旧布局
- train 子集视图如果启用了 `--train-max-samples`，会统一缓存到 run 根目录下的 `_datasets/`

初始化后必须存在：

- `base_prompt.txt`
- `active_prompt.txt`
- `best_prompt.txt`
- `active_patch_set.json`
- `best_patch_set.json`
- `manifest.json`

## 5. Baseline 阶段

### 5.1 Eval Baseline

默认在任何 evolve 开始前，先在 `data/eval` 上做一次 baseline test。

补充：

- 可通过 `--eval-before 0` 关闭

目标：

- 获得初始 held-out 指标
- 作为最终泛化比较的起点

应保存：

- baseline eval metrics
- baseline eval trace

### 5.2 Train Baseline

随后在 `data/train` 上做 baseline train-eval。

目标：

- 生成后续第一轮 reflection 所需的 `yn / ny`
- 获得当前 active prompt 在 train 上的起始表现

应保存：

- `round_000` 的 train trace
- `round_000` 的 train eval
- `round_000` 的 `yn / ny` samples

注意：

- `round_000` 不做 reflection
- `round_000` 不改 prompt

## 6. 单轮 Evolve Workflow

从 `round_001` 开始，每轮按以下流程执行。

### Step 1. 读取当前主线状态

输入：

- `base_prompt.txt`
- `active_patch_set.json`
- `active_prompt.txt`
- 当前 active train eval

输出：

- 当前轮的 `prompt_before.txt`
- `active_patch_set_before.json`

### Step 2. 在 train 结果上准备 reflection 材料

主循环会调用 [reflection.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/reflection.py) 中的 `build_reflection_input(...)`，把当前 active prompt 在 train 上的表现整理成结构化输入。

直接输入：

- `base_prompt`
- `current_prompt`
- `current_active_patch_set`
- 当前 active train eval 的 metrics
- `yn_samples`
- `ny_samples`
- 最近 5 条 history

派生输入：

- 当前 active prompt 相对 parent prompt 的 `fixed_fp/new_fp/fixed_fn/new_fn` 对比
- 当前错误和 delta 错误的 `error_clusters`
- 最近几轮 candidate 相对各自 parent 的 regression 对比

要求：

- `yn` 优先分析
- `ny` 也要完整分析
- 优先从错误簇归纳规则，而不是逐条样本打补丁
- 每个 patch 都要考虑保留已修复错误，并避免新增 regression
- 只分析 train，不分析 eval

写出：

- `reflection/reflection_input.json`

### Step 3. 执行 reflection

这一步根据 `--reflection-mode` 分两种。

#### A. `codex` 模式

系统行为：

1. 写出 `reflection_input.json`
2. 写出 `reflection_status.json`
3. 写出 `state/round_status.json`
4. 停在当前 round，`stop_signal` 为 `waiting_for_codex_reflection`

外部行为：

1. 由 Codex / 主代理 / 人工读取 `reflection_input.json`
2. 生成结构化 `reflection_output.json`
3. 重新 `--resume 1`

恢复行为：

- 如果 `reflection_output.json` 已存在且合法，`run_reflection(...)` 会直接读取并继续 patch merge
- 如果 `reflection_output.json` 已存在但不合法，系统仍会停在当前 round，并要求重新生成合法输出
- 如果通过 [orchestrator.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/orchestrator.py) 启动，则“外部行为”和 `--resume 1` 会被 orchestrator 自动完成

#### B. `llm` 模式

系统行为：

1. 写出 `reflection_input.json`
2. 调用 reflection 模型
3. 生成 `reflection_output.json`
4. 继续后续 patch merge

模型配置：

- 默认沿用主 LLM 配置
- 如果传入 `--reflection-provider` / `--reflection-model` / `--reflection-base-url` / `--reflection-api-key` / `--reflection-auth-mode`，则优先使用 reflection 专用配置

### Step 4. 保存 patch proposal

本轮目录下至少要保存：

- `reflection/reflection_input.json`
- `reflection/reflection_output.json`
- `prompt/prompt_patch.json`
- `prompt/prompt_patch.md`

说明：

- `reflection_output.json` 是 reflection 原始结构化输出，会先经过 normalize
- `prompt_patch.json` 是结构化 patch proposal artifact
- `prompt_patch.md` 是供人工审核的人类可读版本
- 如果 reflection 报错，会写出 `reflection/reflection_error.json`，并在 `state/round_status.json` 中标记为 `reflection_invalid`

### Step 5. 合并 patch

系统将：

- `active_patch_set`
- `patch proposal`

做合并，生成：

- `candidate_patch_set`

合并规则：

1. 将 `reflection_output.json` 规范化为 `operations`
2. 按 operation 优先级尝试加入 candidate patch set
   - `delete_rule`
   - 面向负向章节的 `insert_rule`
   - `rewrite_rule`
   - 面向正向章节的 `insert_rule`
   - `move_rule`
3. 去重
4. 检查单轮变化预算（默认 `25%`，可通过 `--max-candidate-prompt-change-ratio` 调整）
5. 检查总长度是否落在 `base_prompt` 的允许倍率区间内
   - 默认是 `0.7x ~ 1.5x`
   - 可通过 `--base-prompt-min-length-ratio` 和 `--base-prompt-max-length-ratio` 调整

兼容说明：

- 如果 run 中的 `base_prompt.txt` / `active_prompt.txt` / `best_prompt.txt` 仍然带有旧格式的 `### Active Evaluated Patch Rules` overlay，`loop` 启动时会先自动迁移成“无 overlay 的规范化 prompt”，再继续做新的 section-aware merge

### Step 6. 合成 candidate prompt

系统使用：

- `base_prompt + candidate_patch_set`

合成：

- `prompt/prompt_candidate.txt`

合成方式：

- 不再把 patch 渲染成一整段 overlay 挂到 prompt 末尾或 JSON 规则前
- 而是按章节做 section-aware merge
- `add_negative_rules` 优先并入负向规则章节
- `add_positive_rules` 优先并入正向规则章节
- `strengthen_rules / weaken_rules` 会落到最相关章节的 clarifications 区
- `delete_rules` 会优先尝试删除最匹配的原规则块

并写：

- `prompt/prompt_diff.md`

### Step 7. Train 评估

用 `prompt_candidate.txt` 在 `data/train` 上重新跑抽取与评估。

输出：

- `round_xxx/trace/extract_trace.jsonl`
- `round_xxx/eval/eval.json`
- `round_xxx/eval/yn_samples.jsonl`
- `round_xxx/eval/ny_samples.jsonl`

### Step 8. Promote 判断

若 candidate 满足：

1. train 指标优于当前 best
2. 通过 safety gate

则：

- 更新 `active_patch_set.json`
- 更新 `best_patch_set.json`
- 更新 `active_prompt.txt`
- 更新 `best_prompt.txt`

否则：

- 本轮 patch proposal 保留
- 但不进入主线

补充：

- 如果 train 侧存在少量重试耗尽后的 trace error 或 coverage 缺口，系统会把它们记录为 warning，但不再因此自动拒绝 promote
- 只要 candidate 指标更优且没有触发真正的安全回退条件，仍然允许进入主线

## 7. Reflection 流程细节

### 7.1 Reflection 输入协议

`reflection_input.json` 是每轮 prompt 修改的唯一证据包。它由系统生成，外部 reflection 不应自行读取 `data/eval` 或额外样本来发明规则。

核心字段：

- `objective`：当前固定为 `precision-first`
- `base_prompt`：patch 合成的基底 prompt
- `current_prompt`：当前 active prompt，也就是本轮 `prompt_before.txt`
- `current_active_patch_set`：当前已经进入主线的 patch set
- `current_metrics`：当前 active prompt 在 train 上的指标
- `current_prompt_version`：当前 active eval 对应的 prompt version
- `yn_samples`：false positive，预测 yes 但 gold no
- `ny_samples`：false negative，预测 no 但 gold yes
- `error_clusters`：先对每条样本生成 diagnosis，再按 diagnosis 语义聚合后的错误簇
- `history_tail`：最近 5 条历史 round 摘要
- `instructions`：reflection 必须回答和遵守的本轮约束

可选字段：

- `active_vs_reference_delta`：当前 active eval 与 parent/reference eval 的差异
- `recent_candidate_deltas`：最近几轮 candidate 相对 parent 的收益和 regression

`active_vs_reference_delta` 包含：

- `fixed_fp`：上一主线错误、当前已修复的 false positive
- `new_fp`：当前新增的 false positive
- `unchanged_fp`：持续存在的 false positive
- `fixed_fn`：上一主线错误、当前已修复的 false negative
- `new_fn`：当前新增的 false negative
- `unchanged_fn`：持续存在的 false negative
- `metric_delta`：关键指标差异

`error_clusters` 不再依赖任何预设题材 taxonomy。当前做法是：

1. 先让 diagnosis LLM 为每条 `fp/fn` 样本生成 `root_cause`、`secondary_causes`、`missing_or_bad_prompt_rule`
2. 再对这些 diagnosis 文本做 embedding 聚类或 root-cause 文本回退聚合
3. 最终得到按“判错机制”而不是按“题材关键词”组织的 cluster

这些 cluster 只是帮助 reflection 聚合错误，不是可以直接照抄进 prompt 的业务标签。真正的 patch 仍必须抽象成可复用的 prompt 判断规则。

### 7.2 Reflection 分析顺序

推荐分析顺序：

1. 先看 `current_metrics`，确认当前 round 的主要问题是 precision、recall、coverage 还是 trace error
2. 再看 `active_vs_reference_delta`，区分本轮相对 parent 的修复与新增 regression
3. 优先分析 `yn_samples` 和 `new_fp`，找出哪些 one-off 请求被误判为可复用 skill
4. 同步分析 `ny_samples` 和 `new_fn`，找出哪些稳定 schema、workflow、rubric、template、persistent preference 被漏掉
5. 回到 `error_clusters`，把样本级观察提升成 cluster 级根因
6. 检查 `recent_candidate_deltas`，避免重复提出近期已经证明会伤害另一类错误的 patch
7. 对照 `current_prompt`，判断是需要新增规则、改写旧规则、删除误导规则，还是移动规则位置

Reflection 必须优先回答：

- 每类 `yn` 为什么不应该抽取
- 每类 `ny` 为什么应该抽取
- 哪些错误是重复模式，而不是单例噪声
- 哪些 fixed errors 必须保留
- 哪些 new regressions 必须避免
- 当前 prompt 哪些条款太弱、太宽、太窄或歧义

### 7.3 Reflection 输出协议

`reflection_output.json` 必须是严格 JSON object，不能带 Markdown 包裹。推荐 schema：

```json
{
  "yn_root_causes": ["..."],
  "ny_root_causes": ["..."],
  "fp_patterns": ["..."],
  "fn_patterns": ["..."],
  "operations": [
    {
      "op": "insert_rule",
      "target_section": "negative_cases",
      "anchor_text": "",
      "position": "append",
      "content": "Do not extract from generic coding requests unless the user defines a reusable protocol.",
      "rationale": "Reduces false positives on one-off coding help.",
      "priority": 0.9
    }
  ]
}
```

支持的 `op`：

- `insert_rule`：新增规则
- `rewrite_rule`：加强、收窄或软化已有规则
- `delete_rule`：删除过宽、误导或有害规则
- `move_rule`：移动位置错误的规则

支持的 `target_section`：

- `core_principle`
- `evidence_scope`
- `positive_rules`
- `negative_rules`
- `negative_cases`
- `generalization`
- `no_invention`
- `output_construction`
- `confidence_guidance`
- `final_emission_check`
- `language_consistency`
- `json_validity`

支持的 `position`：

- `append`
- `before_anchor`
- `after_anchor`
- `replace`

约束：

- `rewrite_rule`、`delete_rule`、`move_rule` 必须提供 `anchor_text`
- 上述三类操作的 `anchor_text` 必须从 `current_prompt` 原文中逐字复制
- `target_section` 必须是该 `anchor_text` 实际所在章节
- 找不到可靠 anchor 时，不要伪造 anchor，应改用更窄的 `insert_rule`
- 多行规则应保持 Markdown 可读性，子规则用缩进 `- ` bullet
- `priority` 用于合并排序，不是 promote 依据

兼容说明：

- 系统仍能把旧式 `add_negative_rules` / `add_positive_rules` / `strengthen_rules` / `weaken_rules` / `delete_rules` normalize 成 operations
- 新增 reflection 应优先使用 `operations`，不要再产出 legacy list

### 7.4 Patch 质量标准

好的 patch 应该满足：

- 小而可追溯，能从 train 错误模式中找到证据
- 面向抽象错误族，而不是某个文件、产品、项目或单条样本
- 去掉当前实体、日期、路径、项目名后仍然成立
- 优先修正 prompt 的边界、定义、阈值或歧义
- 能解释多个样本，或者能明确保护一个重要的系统性 false negative
- 不通过牺牲另一类已修复错误来修当前错误

坏的 patch 通常表现为：

- 每个样本加一条例外
- 把样本里的业务名词直接写进 prompt
- 把一次性的当前任务参数包装成长期 skill 规则
- 只为了提高 train 指标而改变 prompt 骨架
- 大段重写 prompt，而不是局部 patch
- 没有说明它会影响哪类 `yn` / `ny`

### 7.5 Codex / Orchestrator 细节

普通 `codex` 模式：

1. `loop.py` 写出 `reflection_input.json`
2. `run_reflection(mode="codex")` 发现没有合法 `reflection_output.json`
3. 系统写出 `reflection_status.json`
4. 当前 round 停在 `waiting_for_codex_reflection`
5. 外部生成 `reflection_output.json`
6. 用户重新运行同一 run 的 `--resume 1`
7. `run_reflection(...)` 读取已存在的输出并继续

orchestrator 自动模式：

1. [orchestrator.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/orchestrator.py) 强制把 loop 参数设为 `reflection_mode=codex`
2. loop 停在 `waiting_for_codex_reflection`
3. orchestrator 更新 `reflection_status.json` 为 `running`
4. orchestrator 使用 `llm` 或 `command` backend 生成 `reflection_output.json`
5. 成功后把 `reflection_status.json` 更新为 `completed`
6. 自动设置 `--resume 1` 并继续下一段 loop
7. 重复直到 run 结束或达到 `--codex-max-auto-resumes`

`command` backend 可用环境变量：

- `AUTOSKILL_REFLECTION_INPUT_JSON`
- `AUTOSKILL_REFLECTION_OUTPUT_JSON`
- `AUTOSKILL_REFLECTION_ROUND_DIR`
- `AUTOSKILL_EVOLVE_RUN_ROOT`
- `AUTOSKILL_EVOLVE_PROMPT_ROOT`
- `AUTOSKILL_EVOLVE_LOG_ROOT`
- `AUTOSKILL_EVOLVE_SESSION_STAMP`

`reflection_status.json` 状态：

- `pending`：loop 已停下，等待外部输出
- `running`：orchestrator 正在调用 backend
- `completed`：外部输出已生成并通过 normalize
- `error`：backend 失败，错误信息和日志路径会写入 status

### 7.6 独立 Reflection CLI

如果已经有某轮的 `reflection_input.json`，可以单独运行 reflection：

```bash
python -m autoskill.offline.conversation.self_evolve.reflection \
  --input-json log/self-evolve/<stamp>/<run_name>/round_001/reflection/reflection_input.json \
  --output-json log/self-evolve/<stamp>/<run_name>/round_001/reflection/reflection_output.json \
  --reflection-mode llm
```

说明：

- `llm` 模式会实际生成 `reflection_output.json`
- `codex` 模式不会自动生成结果，只会表达“需要外部写入 output 后再 resume”的状态
- 独立 CLI 只负责 reflection，不负责 patch merge、candidate eval 或 promote

## 8. 结束条件

满足任一条件即可停止：

1. 达到最多 `max-rounds` 轮 evolve
2. 连续若干轮没有提升
3. reflection 无法产生合法 patch proposal
4. safety gate 拒绝当前候选
5. `codex` 模式下当前 round 正在等待外部 `reflection_output.json`

注意：

- 在 `codex` 模式下，“等待外部 reflection”是一个合法中间态，不等于失败
- 此时系统会停在该 round，等待恢复执行
- 如果 run 是由 orchestrator 启动的，这个中间态通常只会短暂存在，随后会被自动消费并继续后续 round

## 9. Final Eval

默认在 evolve 结束后执行 held-out final test。

补充：

- 可通过 `--eval-after 0` 关闭

输入：

- 当前 `best_prompt.txt`

数据：

- `data/eval`
- `data/eval/meta_info.jsonl`

输出：

- final eval trace
- final eval metrics

最终需要比较的是：

1. baseline eval
2. final eval

而不是只看 train。

如果 evolve 中途停止，但你想单独用当前某个 prompt 做一次独立评估，可以使用：

- [eval.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/eval.py)

示例：

```bash
python -m autoskill.offline.conversation.self_evolve.eval \
  --run-root log/self-evolve/<stamp>/<run_name> \
  --prompt-source best \
  --dataset eval
```

补充：

- `--prompt-source best` 会使用 run 根目录下当前的 `best_prompt.txt`
- 也可以改成 `active`、`round_candidate`、`round_before`
- 输出会写到 run 根目录下单独的 `manual_eval_*` 子目录
- 这个入口只做评估，不会修改主线状态

## 10. 产物要求

### 10.1 Run 根目录

必须保留：

- `base_prompt.txt`
- `active_prompt.txt`
- `best_prompt.txt`
- `active_patch_set.json`
- `best_patch_set.json`
- `manifest.json`
- `history.jsonl`

建议额外保存：

- `baseline_eval_metrics.json`
- `final_eval_metrics.json`

### 10.2 Round 目录

每轮至少保存：

- `prompt/prompt_before.txt`
- `prompt/prompt_candidate.txt`
- `prompt/prompt_diff.md`
- `prompt/active_patch_set_before.json`
- `prompt/candidate_patch_set.json`
- `reflection/reflection_input.json`
- `reflection/reflection_output.json`
- `prompt/prompt_patch.json`
- `prompt/prompt_patch.md`
- `state/round_summary.json`

如果是 `codex` 模式中途等待，还应保存：

- `reflection/reflection_status.json`

说明：

- `reflection_status.json` 初始通常为 `pending`
- 如果通过 orchestrator 自动接管，状态还可能变为 `running` / `completed` / `error`
- 当前 round 目录采用分组结构，默认会看到 `prompt/`、`reflection/`、`trace/`、`eval/`、`state/` 这些子目录
- 历史扁平 round 目录在 `--resume 1` 时会自动迁移到这套分组结构

### 10.3 Log 目录

统一根目录下的评估/日志子目录至少保存：

- `trace/extract_trace.jsonl`
- `eval/eval.json`
- `eval/yn_samples.jsonl`
- `eval/ny_samples.jsonl`

### 10.4 Train 子集视图

当传入 `--train-max-samples N` 时，系统不会修改原始 `data/train`，而是在 run 根目录下创建一个可复用的数据集视图：

- `_datasets/train_first_<N>/`

作用：

- 让现有 extraction 入口只处理前 `N` 条 train 样本
- 所有 round 共享同一份子集视图，而不是每轮各建一份

实现细节：

- 默认优先使用符号链接
- 如果符号链接不可用，则退化为硬链接
- 只有前两者都失败时才会复制文件

因此：

- 这部分主要占用的是磁盘目录项，不是运行内存
- 在大多数本地环境下，新增占用会明显小于“每轮复制一遍原文件”

### 10.5 Run State Ops

当某个历史 round 的 candidate 需要被重新认定为主线，或者需要把 run 回滚到某个已 promote 的轮次时，可以使用：

- [state_ops.py](/Users/ljs/AutoSkill/autoskill/offline/conversation/self_evolve/state_ops.py)

常见命令：

```bash
python -m autoskill.offline.conversation.self_evolve.state_ops \
  --run-root log/self-evolve/<stamp>/<run_name> \
  show-state
```

```bash
python -m autoskill.offline.conversation.self_evolve.state_ops \
  --run-root log/self-evolve/<stamp>/<run_name> \
  rebase \
  --round 1 \
  --archive-later-rounds 1
```

```bash
python -m autoskill.offline.conversation.self_evolve.state_ops \
  --run-root log/self-evolve/<stamp>/<run_name> \
  rollback \
  --round 1 \
  --archive-later-rounds 1
```

语义：

- `show-state`：查看当前主线状态
- `rebase --round N`：把 `round_NNN` 的 candidate prompt / patch / eval 强行提升为新的主线
- `rollback --round N`：回到一个已经 promote 过的历史主线轮次；如果该轮当时并未 promote，应改用 `rebase`

副作用：

- 会更新 run 根目录下的 `active_prompt.txt`、`best_prompt.txt`、`active_patch_set.json`、`best_patch_set.json`、`best_metrics.json`
- 会更新 `manifest.json` 与 `history.jsonl`
- 如果启用 `--archive-later-rounds 1`，会把目标轮次之后的 `round_*` 和 `_stores/round_*` 归档到 `run_root/_state_ops/archive/`

## 11. 人工审核重点

在 `codex` 模式下，外部 reflection 的审核重点是：

1. 当前 `yn` 是否主要来自几类重复模式
2. 当前 `ny` 是否说明规则收得过头
3. 某条新 patch 是否真的有 train 证据支持
4. 某条 patch 是否会和已有 patch 冲突
5. 当前 patch 是否在偷偷改变 prompt 骨架
6. prompt 长度是否正在异常膨胀或收缩

## 12. 一句话执行摘要

当前 workflow 的执行顺序是：

**先在 `data/eval` 做 baseline test，再在 `data/train` 上做最多 8 轮 patch-based evolve；每一轮的 reflection 可以由 `codex` 外部完成，也可以由 `llm` 自动完成；如果使用 orchestrator，则 `codex` 模式下的外部 reflection 与 `resume` 会被自动串起来；系统负责抽取、评估、合并 patch 和保存产物；最后再用最终 best prompt 在 `data/eval` 上做 final test。**
