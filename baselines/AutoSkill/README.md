# AutoSkill: Experience-Driven Lifelong Learning via Skill Self-Evolution

English | [中文](README.zh-CN.md)

<p align="center">
  <img src="imgs/AutoSkill_logo.png" alt="AutoSkill Logo" width="320" />
</p>

<p align="center">
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/Maintained%20By-ICALK-0A66C2" alt="Maintained By ICALK" /></a>
  <a href="https://arxiv.org/abs/2603.01145"><img src="https://img.shields.io/badge/arXiv-2603.01145-b31b1b.svg" alt="arXiv 2603.01145" /></a>
  <a href="https://github.com/ECNU-ICALK/AutoSkill"><img src="https://img.shields.io/badge/GitHub-ECNU--ICALK%2FAutoSkill-181717?logo=github" alt="GitHub ECNU-ICALK/AutoSkill" /></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License MIT" /></a>
</p>

AutoSkill is a practical implementation of **Experience-driven Lifelong Learning (ELL)**.
It learns from real interaction experience (dialogue + agents), automatically creates reusable Skills,
and continuously evolves existing Skills through merge + version updates.

![AutoSkill Framework](imgs/Framework.png)

## News

- **2026-05-09**: Added the installable **AutoSkill Local Skill Manager** (`skills/autoskill`) for maintaining local Agent Skill files after sessions, including reusable-experience triage, similar-skill search, and `discard` / `improve` / `merge` / `create` decisions.
- **2026-03-23**: **SkillEvo 1.0** released (Enabling models to iteratively self-evolve Skills through replay, evaluation, mutation, and promotion).
- **2026-03-13**: **AutoSkill4Doc 1.0** released (Being expext by extracting skills from document/research paper).
- **2026-03-01**: Added offline skill extraction from archived conversations (See Skills in SkillBank/CovSkill).
- **2025-02-26**: **AutoSkill4OpenClaw 1.0** released (Extracting skills from trajectory of OpenClaw).
- **2025-02-04**: **AutoSkill 1.0** released (Extracting skills from dialogues in time).

## Table of Contents

- [News](#news)
- [1. Project Overview](#1-project-overview)
- [2. Main Components](#2-main-components)
- [3. Skill Lifecycle Example](#3-skill-lifecycle-example)
- [4. Documentation Map](#4-documentation-map)
- [5. Repository Structure (Top Level)](#5-repository-structure-top-level)
- [6. Star History](#6-star-history)
- [7. Citation](#7-citation)
- [8. Contributions and Acknowledgments](#8-contributions-and-acknowledgments)

## 1. Project Overview

- **Experience-driven continuous skill evolution**: extracts reusable capabilities directly from real user interactions and agent traces, then continuously maintains versioned skills so the system aligns with user needs over time.
- **Universal skill format**: uses the Agent Skill artifact (`SKILL.md`) with explainability and editability. Skills remain readable, reviewable, and manually revisable.
- **Offline extraction from completed data**: existing chats and trajectories can be imported directly for offline skill extraction; there is no need to replay the original interaction.
- **Long-term capability value**: AutoSkill turns short-term interaction signals into long-term capability assets that can be reused across runtimes.

## 2. Main Components

- [`autoskill/`](autoskill/README.md): core SDK, Web UI, OpenAI-compatible proxy, online skill evolution, offline conversation extraction, and offline trajectory extraction.
- [`AutoSkill4Doc/`](AutoSkill4Doc/README.md): standalone document-to-skill pipeline for extracting reusable skills from papers, manuals, and domain documents.
- [`AutoSkill4OpenClaw/`](AutoSkill4OpenClaw/README.md): OpenClaw integration for trajectory-driven skill evolution and native skill mirroring.
- [`SkillEvo/`](SkillEvo/README.md): replay, evaluation, mutation, and promotion framework for iterative skill self-evolution.

## 3. Skill Lifecycle Example

### A) Auto Decision + Feedback-triggered Extraction & Skill Management (v0.1.0)

If the user only asks to "write a report" and gives no stable preference/correction, AutoSkill does **not** create a new skill
(it outputs an empty extraction result) to avoid noisy, generic skills.

When the user adds durable constraints (for example: "do not hallucinate"), AutoSkill extracts or merges a skill into version `v0.1.0`.
Skill management is backend-first (automatic add/merge), with optional human edit/save/delete of `SKILL.md`.

![Skill Extraction (Daily)](imgs/skill_extraction.png)
*Caption: Daily scenario — reusable writing constraints are extracted into a new skill (`v0.1.0`).*

![Skill Extraction (Science)](imgs/science_skill_extraction.png)
*Caption: Science scenario — reusable lab/process constraints (for example hard limits and mandatory SOP steps) are extracted as a skill (`v0.1.0`).*

### B) Skill Update (v0.1.1)

When user feedback adds new constraints or changes priorities in later turns, AutoSkill updates the existing skill (instead of creating duplicates)
and evolves the version from `v0.1.0` to `v0.1.1`.

![Skill Update (Daily)](imgs/skill_update.png)
*Caption: Daily scenario — later user feedback updates constraints and evolves the skill to `v0.1.1`.*

![Skill Update (Science)](imgs/science_skill_update.png)
*Caption: Science scenario — follow-up technical feedback updates the existing science skill instead of creating duplicates (`v0.1.1`).*

### C) Skill Usage

For the next similar task (for example, writing a **government report about a self-evolving agent**), the updated skill is retrieved and used
to generate outputs aligned with user expectations.

![Skill Usage (Daily)](imgs/skill_utilize.png)
*Caption: Daily scenario — the evolved skill is retrieved and reused in the next similar task.*

![Skill Usage (Science)](imgs/science_skill_utilize.png)
*Caption: Science scenario — the evolved science skill is retrieved for subsequent domain-consistent requests.*

## 4. Documentation Map

- Core runtime, SDK, Web UI, proxy, and offline conversation/trajectory extraction:
  [`autoskill/README.md`](autoskill/README.md)
- Document-native extraction pipeline:
  [`AutoSkill4Doc/README.md`](AutoSkill4Doc/README.md)
- OpenClaw integration and deployment:
  [`AutoSkill4OpenClaw/README.md`](AutoSkill4OpenClaw/README.md)
- Skill replay, evaluation, mutation, and promotion:
  [`SkillEvo/README.md`](SkillEvo/README.md)

## 5. Repository Structure (Top Level)

- `autoskill/`: core SDK and runtime.
- `AutoSkill4Doc/`: standalone document-to-skill pipeline.
- `AutoSkill4OpenClaw/`: OpenClaw integration.
- `SkillEvo/`: iterative skill self-evolution framework.
- `examples/`: runnable entrypoints and demos.
- `SkillBank/`: default local skill storage root.
- `data/`: evaluation and sample data.
- `tests/`: automated tests.
- `web/`: local Web UI assets.
- `imgs/`: README figures and demo images.

## 6. Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ECNU-ICALK/AutoSkill&type=Date)](https://star-history.com/#ECNU-ICALK/AutoSkill&Date)

## 7. Citation

If you use AutoSkill in academic work, technical reports, or demos, please cite:

```bibtex
@software{autoskill_2026,
  author = {Yutao Yang, Junsong Li, Qianjun Pan, Bihao Zhan, Yuxuan Cai, Lin Du, Xin Li, Bo Zhang, Qin Chen, Jie Zhou, Kai Chen, Liang He},
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

## 8. Contributions and Acknowledgments

Institutions: Shanghai AI Laboratory, School of Computer Science at East China Normal University

Core Authors: Yutao Yang

Contribution: Junsong Li, Qianjun Pan, Bihao Zhan, Yuxuan Cai, Lin Du

Lead Authors: Jie Zhou, Kai Chen, Liang He

Scientific Directors: Xin Li, Bo Zhang, Qin Chen
