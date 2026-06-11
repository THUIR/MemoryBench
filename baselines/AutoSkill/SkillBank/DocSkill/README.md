# DocSkill

该目录保存 AutoSkill4Doc 生成的可见技能树。

## 结构

- `<domain_root>/总技能/SKILL.md`：领域总导航技能
- `<domain_root>/Family技能/<family_name>/总技能/SKILL.md`：family 总导航技能
- `<domain_root>/Family技能/<family_name>/一级技能|二级技能|微技能/<名称>/SKILL.md`：分层技能
- `.runtime/document_registry/`：离线文档 registry
- `.runtime/library_manifest.json`：可见技能树索引

## 生成逻辑

1. 文档先经过 ingest / extract / compile / register_versions。
2. register_versions 持久化 registry 后，再把当前有效 skill 同步成领域 -> family -> 分层技能树。
3. 具体技能目录来自当前有效 SkillSpec/最终 store skill；`references/evidence.*` 来自对应 SupportRecord 和 DocumentRecord。
4. 领域总技能和 family 总技能不是再次抽取出来的独立文档，而是根据当前有效技能自动合成的导航技能。
5. `children_manifest.json` / `children_map.md` / `domain_manifest.json` 提供机器可读索引与人读目录。

## 使用建议

- 为了稳定得到期望目录名，建议在构建时显式传 `--family-name`。
- 如需保留 profile / taxonomy 信息，建议同时传 `--profile-id` 和 `--taxonomy-axis`。
- 已导出的 `总技能/`、`一级技能/`、`二级技能/`、`微技能/`、`references/` 不应该再作为源文档回灌；ingest 会自动跳过这些生成产物。

## 已同步领域

- [心理咨询](心理咨询/总技能/SKILL.md) (5 family)
  - [人本-存在主义](心理咨询/Family技能/人本-存在主义/总技能/SKILL.md) (6 技能)
  - [后现代主义](心理咨询/Family技能/后现代主义/总技能/SKILL.md) (9 技能)
  - [心理动力学](心理咨询/Family技能/心理动力学/总技能/SKILL.md) (17 技能)
  - [行为主义](心理咨询/Family技能/行为主义/总技能/SKILL.md) (11 技能)
  - [认知行为疗法](心理咨询/Family技能/认知行为疗法/总技能/SKILL.md) (68 技能)
