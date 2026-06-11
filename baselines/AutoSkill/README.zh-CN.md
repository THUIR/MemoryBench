# AutoSkill: 基于技能自进化的经验驱动终身学习

[English](README.md) | 中文

<p align="center">
  <img src="imgs/AutoSkill_logo.png" alt="AutoSkill Logo" width="320" />
</p>

<p align="center">
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/Maintained%20By-ICALK-0A66C2" alt="Maintained By ICALK" /></a>
  <a href="https://arxiv.org/abs/2603.01145"><img src="https://img.shields.io/badge/arXiv-2603.01145-b31b1b.svg" alt="arXiv 2603.01145" /></a>
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/GitHub-ECNU--ICALK%2FAutoSkill-181717?logo=github" alt="GitHub ECNU-ICALK/AutoSkill" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" /></a>
</p>

AutoSkill 是 **Experience-driven Lifelong Learning（ELL，经验驱动终身学习）** 的工程化实践。
它从真实交互经验（对话 + agent）中学习，自动生成可复用技能，并通过合并与版本演进持续优化已有技能。

![AutoSkill Framework](imgs/Framework.png)

## News

- **2026-05-09**：新增可安装的 **AutoSkill Local Skill Manager**（`skills/autoskill`），用于在会话结束后维护本地 Agent Skill 文件，支持可复用经验分流、相似技能查找，以及 `discard` / `improve` / `merge` / `create` 决策。
- **2026-03-23**：发布 **SkillEvo 1.0**（支持模型通过 replay、评测、变异与晋升机制，对 Skill 进行自我迭代进化）。
- **2026-03-13**：发布 **AutoSkill4Doc 1.0**（通过文档/研究论文抽取技能，持续完善中）。
- **2026-03-01**：新增离线从历史对话抽取技能功能（示例可见 `SkillBank/CovSkill`）。
- **2025-02-26**：发布 **AutoSkill4OpenClaw 1.0**（支持从 OpenClaw 轨迹中抽取技能）。
- **2025-02-04**：发布 **AutoSkill 1.0**（支持随时间从对话中抽取技能）。

## 目录

- [News](#news)
- [1. 项目总览](#1-项目总览)
- [2. 主要组成模块](#2-主要组成模块)
- [3. 技能生命周期示例](#3-技能生命周期示例)
- [4. 文档导航](#4-文档导航)
- [5. 仓库结构（顶层）](#5-仓库结构顶层)
- [6. Star History](#6-star-history)
- [7. 引用（Citation）](#7-引用citation)
- [8. 贡献与致谢](#8-贡献与致谢)

## 1. 项目总览

- **经验驱动技能持续进化**：从真实用户交互和 agent 轨迹中抽取可复用能力，并通过版本演进持续维护，使系统越来越贴合用户需求。
- **通用技能格式**：采用 Agent Skill 形态（`SKILL.md`），结构清晰、内容可审阅、可按需人工修改。
- **对已结束数据的离线抽取**：已有对话和轨迹可以直接导入并离线抽取技能，无需重新回放交互过程。
- **长期能力价值**：AutoSkill 将短期交互沉淀为长期能力资产，支持跨运行时迁移与复用。

## 2. 主要组成模块

- [`autoskill/`](autoskill/README.zh-CN.md)：核心 SDK、Web UI、OpenAI 兼容代理、在线技能演化、离线对话抽取与离线轨迹抽取。
- [`AutoSkill4Doc/`](AutoSkill4Doc/README.zh-CN.md)：独立的文档到技能抽取流水线，适用于论文、手册和领域文档。
- [`AutoSkill4OpenClaw/`](AutoSkill4OpenClaw/README.zh-CN.md)：OpenClaw 集成，用于轨迹驱动的技能演化与原生技能镜像。
- [`SkillEvo/`](SkillEvo/README.md)：通过 replay、评测、变异与晋升机制实现技能的迭代自进化。

## 3. 技能生命周期示例

### A) 自动判断 + 反馈触发抽取与技能管理（v0.1.0）

如果用户只是提出“写一份报告”这类通用一次性请求，且没有给出稳定偏好或纠偏反馈，
AutoSkill 会默认不新增技能（抽取结果为空），避免产生噪声技能。

当用户给出可复用的稳定约束（例如“不要幻觉”）时，AutoSkill 会触发抽取或与已有技能合并，形成 `v0.1.0`。
技能管理以后端自动为主（自动新增/合并），并支持人工编辑保存或删除 `SKILL.md`。

![技能抽取（日常场景）](imgs/skill_extraction.png)
*图注：日常场景中，可复用的写作约束被抽取为新技能（`v0.1.0`）。*

![技能抽取（科研场景）](imgs/science_skill_extraction.png)
*图注：科研场景中，可复用的实验/流程约束（如硬性阈值、必选 SOP 步骤）被抽取为技能（`v0.1.0`）。*

### B) 技能更新（v0.1.1）

后续交互中当用户继续给出新增约束或偏好变化时，AutoSkill 会优先更新已有技能而不是产生重复技能，
将版本从 `v0.1.0` 演进到 `v0.1.1`。

![技能更新（日常场景）](imgs/skill_update.png)
*图注：日常场景中，后续用户反馈持续补充约束，技能演进到 `v0.1.1`。*

![技能更新（科研场景）](imgs/science_skill_update.png)
*图注：科研场景中，新增技术反馈会更新既有技能而非新增重复技能（`v0.1.1`）。*

### C) 技能使用

当再次出现类似任务（例如撰写一份**自进化智能体的政府报告**）时，系统会检索并使用该技能，
输出更贴合用户需求的结果。

![技能使用（日常场景）](imgs/skill_utilize.png)
*图注：日常场景中，演进后的技能会在后续相似任务中被检索并复用。*

![技能使用（科研场景）](imgs/science_skill_utilize.png)
*图注：科研场景中，演进后的科研技能会在后续同类任务中被检索并复用。*

## 4. 文档导航

- 核心运行时、SDK、Web UI、代理服务、离线对话抽取和离线轨迹抽取：
  [`autoskill/README.zh-CN.md`](autoskill/README.zh-CN.md)
- 文档到技能抽取流水线：
  [`AutoSkill4Doc/README.zh-CN.md`](AutoSkill4Doc/README.zh-CN.md)
- OpenClaw 集成与部署：
  [`AutoSkill4OpenClaw/README.zh-CN.md`](AutoSkill4OpenClaw/README.zh-CN.md)
- 技能 replay、评测、变异与晋升：
  [`SkillEvo/README.md`](SkillEvo/README.md)

## 5. 仓库结构（顶层）

- `autoskill/`：核心 SDK 与运行时。
- `AutoSkill4Doc/`：独立文档到技能流水线。
- `AutoSkill4OpenClaw/`：OpenClaw 集成。
- `SkillEvo/`：技能自进化框架。
- `examples/`：可直接运行的入口与示例。
- `SkillBank/`：默认本地技能存储目录。
- `data/`：评测与样例数据。
- `tests/`：自动化测试。
- `web/`：本地 Web UI 资源。
- `imgs/`：README 图片与示例图。

## 6. Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ECNU-ICALK/AutoSkill&type=Date)](https://star-history.com/#ECNU-ICALK/AutoSkill&Date)

## 7. 引用（Citation）

如果你在论文、技术报告或公开演示中使用了 AutoSkill，建议引用：

```bibtex
@software{autoskill_2026,
  author = {Yutao Yang, Junsong Li, Qianjun Pan, Bihao Zhan, Yuxuan Cai, Du Lin, Xin Li, Bo Zhang, Qin Chen, Jie Zhou, Kai Chen, Liang He},
  title = {AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution},
  year = {2026},
  url = {https://github.com/ECNU-ICALK/AutoSkill},
  note = {GitHub repository}
}

@misc{yang2026autoskillexperiencedrivenlifelonglearning,
  title={AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution},
  author={Yutao Yang and Junsong Li and Qianjun Pan and Bihao Zhan and Yuxuan Cai and Lin Du and Jie Zhou and Kai Chen and Qin Chen and Xin Li and Bo Zhang and Liang He},
  year={2026},
  eprint={2603.01145},
  archivePrefix={arXiv},
  primaryClass={cs.AI},
  url={https://arxiv.org/abs/2603.01145},
}
```


## 8. 贡献与致谢

机构：上海人工智能实验室、华东师范大学计算机学院

核心作者：杨宇涛

贡献者：李俊松、潘前俊、詹必豪、蔡於轩、杜霖

领衔作者：周杰、陈恺、贺樑

学术指导：李鑫、张铂、陈琴
