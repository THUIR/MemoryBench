from __future__ import annotations

import json
import unittest

from autoskill.llm.base import LLM
from AutoSkill4Doc.document.windowing import build_windows_for_record
from AutoSkill4Doc.ingest import HeuristicDocumentIngestor, ingest_document, parse_sections_from_text
from AutoSkill4Doc.models import DocumentRecord, DocumentSection, TextSpan


class _OutlineMockLLM(LLM):
    def complete(self, *, system: str | None, user: str, temperature: float = 0.0) -> str:
        _ = system, temperature
        payload = json.loads(user)
        if "candidates" in payload:
            return json.dumps(
                {
                    "headings": [
                        {"candidate_index": 0, "level": 1},
                        {"candidate_index": 1, "level": 2},
                        {"candidate_index": 2, "level": 2},
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"skills": []}, ensure_ascii=False)


class DocumentWindowingTest(unittest.TestCase):
    def test_recommended_ingest_filters_noise_sections_and_builds_strict_windows(self) -> None:
        result = ingest_document(
            data="""
# 摘要
这是一段摘要说明，不应进入主窗口。

# 第2阶段目标
阶段目标是识别自动思维并建立本次会谈目标。

认知重构用于检验自动思维中的证据。

使用思维记录表整理支持证据和替代解释。

安排家庭作业，在会谈后继续练习。
""".strip(),
            title="CBT Stage Window",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual(len(result.text_units), 1)
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(len(result.windows), 1)
        window = result.windows[0]
        self.assertEqual(window.strategy, "strict")
        self.assertNotEqual(window.section_heading, "摘要")
        self.assertIn("认知重构", window.text)
        self.assertIn("家庭作业", window.text)

    def test_dialogue_heavy_excerpt_is_dropped_from_main_windows(self) -> None:
        result = ingest_document(
            data="""
# 对话摘录
咨询师：你现在最担心什么？
来访者：我一直睡不好。
咨询师：最近有没有伤害自己的想法？

# 风险评估
先评估当前自伤风险和他伤风险。

再确认安全计划与紧急联系人。

记录转介与后续跟进要求。
""".strip(),
            title="Risk Intake",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual(len(result.windows), 1)
        window = result.windows[0]
        self.assertEqual(window.section_heading, "风险评估")
        self.assertNotIn("咨询师：", window.text)
        self.assertIn("安全计划", window.text)

    def test_process_like_section_without_explicit_anchor_falls_back_to_local_window(self) -> None:
        result = ingest_document(
            data="""
# 干预流程
1. 先明确当前目标。
2. 再做现实检验。
3. 记录替代想法。
4. 布置练习与回顾方式。
""".strip(),
            title="Process Fallback",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual(len(result.windows), 1)
        window = result.windows[0]
        self.assertEqual(window.paragraph_start, 0)
        self.assertEqual(window.paragraph_end, 0)
        self.assertIn("现实检验", window.text)
        self.assertIn("布置练习", window.text)

    def test_chunk_strategy_marks_windows_as_chunk(self) -> None:
        result = ingest_document(
            data="""
# 干预流程
第一步先明确当前目标并建立任务边界。

第二步进行现实检验，梳理支持与反证。

第三步记录替代解释与后续练习。
""".strip(),
            title="Chunk Window",
            domain="psychology",
            dry_run=True,
            extract_strategy="chunk",
        )

        self.assertEqual(len(result.windows), 1)
        self.assertEqual(result.windows[0].strategy, "chunk")

    def test_invalid_extract_strategy_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported extract strategy"):
            ingest_document(
                data="""
# 干预流程
1. 先明确当前目标。
2. 再做现实检验。
""".strip(),
                title="Bad Strategy",
                domain="psychology",
                dry_run=True,
                extract_strategy="chunks",
            )

    def test_numbered_subsections_preserve_hierarchy_context(self) -> None:
        sections = parse_sections_from_text(
            """
3 认知重构

3.1 自动思维识别
先识别自动思维和触发事件。

3.2 证据检验
再评估支持证据、反证和替代解释。
""".strip(),
            default_title="CBT",
        )

        self.assertEqual(["3 认知重构", "3.1 自动思维识别"], sections[0].metadata["heading_path"])
        self.assertEqual("3 认知重构", sections[1].metadata["parent_heading"])

        result = ingest_document(
            data="""
3 认知重构

3.1 自动思维识别
先识别自动思维和触发事件。

3.2 证据检验
再评估支持证据、反证和替代解释。
""".strip(),
            title="CBT Hierarchy",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual(1, len(result.windows))
        first = result.windows[0]
        self.assertEqual("3 认知重构", first.section_heading)
        self.assertEqual(["3 认知重构"], first.metadata["heading_path"])
        self.assertIn("3.1 自动思维识别", list(first.metadata.get("subsection_headings") or []))
        self.assertIn("3.2 证据检验", list(first.metadata.get("subsection_headings") or []))

    def test_markdown_numbered_subsections_use_numeric_hierarchy(self) -> None:
        sections = parse_sections_from_text(
            """
# 4 治疗过程

# 4.1关系建立阶段
本阶段先建立关系并完成初始评估。

# 4.2解释与经验重构阶段
本阶段围绕核心主题做解释与经验重构。
""".strip(),
            default_title="PDT",
        )

        self.assertEqual(2, len(sections))
        self.assertEqual(["4 治疗过程", "4.1关系建立阶段"], sections[0].metadata["heading_path"])
        self.assertEqual("4 治疗过程", sections[0].metadata["parent_heading"])
        self.assertEqual("4.1", sections[0].metadata["heading_number"])
        self.assertEqual("markdown_decimal", sections[0].metadata["heading_kind"])

        result = ingest_document(
            data="""
# 4 治疗过程

# 4.1关系建立阶段
本阶段先建立关系并完成初始评估。

# 4.2解释与经验重构阶段
本阶段围绕核心主题做解释与经验重构。
""".strip(),
            title="Markdown Hierarchy",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual(1, len(result.windows))
        first = result.windows[0]
        self.assertEqual("4 治疗过程", first.section_heading)
        self.assertEqual(["4 治疗过程"], first.metadata["heading_path"])
        self.assertIn("4.1关系建立阶段", list(first.metadata.get("subsection_headings") or []))
        self.assertIn("4.2解释与经验重构阶段", list(first.metadata.get("subsection_headings") or []))

    def test_cn_enum_and_paren_subsections_use_neighbor_context(self) -> None:
        sections = parse_sections_from_text(
            """
# 4 治疗过程

一、关系建立
本部分用于建立治疗关系。

二、解释阶段
本部分用于解释与重构。

# 4.1 关系建立阶段

（1）初始评估
先完成初始评估。

（2）建立契约
再建立基本咨询契约。
""".strip(),
            default_title="Mixed Hierarchy",
        )

        self.assertEqual(["4 治疗过程", "一、关系建立"], sections[0].metadata["heading_path"])
        self.assertEqual("4 治疗过程", sections[0].metadata["parent_heading"])
        self.assertEqual(["4 治疗过程", "二、解释阶段"], sections[1].metadata["heading_path"])
        self.assertEqual(["4 治疗过程", "4.1 关系建立阶段", "（1）初始评估"], sections[2].metadata["heading_path"])
        self.assertEqual("4.1 关系建立阶段", sections[2].metadata["parent_heading"])
        self.assertEqual(["4 治疗过程", "4.1 关系建立阶段", "（2）建立契约"], sections[3].metadata["heading_path"])

    def test_same_style_siblings_recover_after_numbered_substeps(self) -> None:
        sections = parse_sections_from_text(
            """
# 5.咨询方案

# （一）咨询原理和方法：系统脱敏疗法
系统脱敏疗法用于逐级暴露与放松训练。

# 1．学习放松技巧
先学习肌肉放松训练。

# 2．建构焦虑等级
再建构焦虑等级表。

# (二）时间和收费
学校咨询每周两次，每次五十分钟。

# (三）双方责任、权利和义务
明确双方责任与保密要求。
""".strip(),
            default_title="Sibling Recovery",
        )

        by_heading = {section.heading: list(section.metadata.get("heading_path") or []) for section in sections}
        self.assertEqual(["5.咨询方案", "（一）咨询原理和方法：系统脱敏疗法"], by_heading["（一）咨询原理和方法：系统脱敏疗法"])
        self.assertEqual(["5.咨询方案", "（一）咨询原理和方法：系统脱敏疗法", "1．学习放松技巧"], by_heading["1．学习放松技巧"])
        self.assertEqual(["5.咨询方案", "(二）时间和收费"], by_heading["(二）时间和收费"])
        self.assertEqual(["5.咨询方案", "(三）双方责任、权利和义务"], by_heading["(三）双方责任、权利和义务"])

    def test_reference_like_body_is_skipped_even_without_reference_heading(self) -> None:
        result = ingest_document(
            data="""
# 研究摘要
这是正文说明。

文献列表
[1] Beck, A. T. (1979). Cognitive Therapy and the Emotional Disorders.
[2] Ellis, A. (1962). Reason and Emotion in Psychotherapy.
[3] https://doi.org/10.1000/example
[4] Dobson, K. S. (2010). Handbook of Cognitive-Behavioral Therapies.
""".strip(),
            title="Reference Filter",
            domain="psychology",
            dry_run=True,
        )

        self.assertEqual([], result.windows)

    def test_outline_llm_fallback_recovers_parent_and_subsections(self) -> None:
        result = ingest_document(
            data="""
Intervention Framework

Focus Reset
先帮助来访者收束当前焦点并明确本次目标。

Evidence Review
再检查支持证据、反证和替代解释。
""".strip(),
            title="Outline Fallback",
            domain="psychology",
            dry_run=True,
            ingestor=HeuristicDocumentIngestor(llm=_OutlineMockLLM()),
        )

        self.assertEqual(1, len(result.windows))
        self.assertEqual("Intervention Framework", result.windows[0].section_heading)
        self.assertEqual(["Intervention Framework"], result.windows[0].metadata["heading_path"])
        self.assertEqual("", result.windows[0].metadata["parent_heading"])
        self.assertIn("Focus Reset", list(result.windows[0].metadata.get("subsection_headings") or []))
        self.assertIn("Evidence Review", list(result.windows[0].metadata.get("subsection_headings") or []))

    def test_outline_llm_fallback_can_refine_low_confidence_partial_structure(self) -> None:
        result = ingest_document(
            data="""
3 认知重构

自动思维识别
先识别自动思维和触发事件。

证据检验
再评估支持证据、反证和替代解释。
""".strip(),
            title="Partial Outline",
            domain="psychology",
            dry_run=True,
            ingestor=HeuristicDocumentIngestor(llm=_OutlineMockLLM()),
        )

        self.assertEqual(1, len(result.windows))
        self.assertEqual("3 认知重构", result.windows[0].section_heading)
        self.assertEqual(["3 认知重构"], result.windows[0].metadata["heading_path"])
        self.assertIn("自动思维识别", list(result.windows[0].metadata.get("subsection_headings") or []))
        self.assertIn("证据检验", list(result.windows[0].metadata.get("subsection_headings") or []))

    def test_outline_llm_reclassifies_detected_heading_candidates(self) -> None:
        result = ingest_document(
            data="""
# 4 治疗过程

# 4.1 关系建立阶段
先建立关系。

# 4.2 解释阶段
再做解释与重构。
""".strip(),
            title="Outline Classifier",
            domain="psychology",
            dry_run=True,
            ingestor=HeuristicDocumentIngestor(llm=_OutlineMockLLM()),
        )

        self.assertEqual(1, len(result.windows))
        first = result.windows[0]
        self.assertEqual("4 治疗过程", first.section_heading)
        self.assertEqual(["4 治疗过程"], first.metadata["heading_path"])
        self.assertIn("4.1 关系建立阶段", list(first.metadata.get("subsection_headings") or []))
        self.assertIn("4.2 解释阶段", list(first.metadata.get("subsection_headings") or []))

    def test_parse_sections_filters_front_matter_and_backmatter_noise(self) -> None:
        sections = parse_sections_from_text(
            """
# A Case of Counseling

Author Name1,2
Email: author@example.com

# Abstract
This is abstract text.

# 1.一般资料

# （一）基本情况
基本情况内容。

# 2．主诉和个人陈述

# （一）主诉
主诉内容。

# 3.评估与诊断
评估内容。

# 4.咨询目标
咨询目标内容。

# 5.咨询方案

# （一）咨询原理和方法：系统脱敏疗法
咨询原理内容。

# 1．学习放松技巧
学习放松技巧内容。

# 2．建构焦虑等级
建构焦虑等级内容。

# 参考文献 (References)
[1] Example reference

# 期刊投稿者将享受如下服务：
推广内容
""".strip(),
            default_title="Sample",
        )

        headings = [section.heading for section in sections]
        self.assertNotIn("Abstract", headings)
        self.assertNotIn("Author Name1,2", headings)
        self.assertNotIn("参考文献 (References)", headings)
        self.assertNotIn("期刊投稿者将享受如下服务：", headings)
        by_heading = {section.heading: list(section.metadata.get("heading_path") or []) for section in sections}
        self.assertEqual(["2．主诉和个人陈述", "（一）主诉"], by_heading["（一）主诉"])
        self.assertEqual(["5.咨询方案", "（一）咨询原理和方法：系统脱敏疗法", "1．学习放松技巧"], by_heading["1．学习放松技巧"])
        self.assertEqual(["5.咨询方案", "（一）咨询原理和方法：系统脱敏疗法", "2．建构焦虑等级"], by_heading["2．建构焦虑等级"])

    def test_short_adjacent_windows_are_merged_and_tiny_strict_slice_falls_back(self) -> None:
        result = ingest_document(
            data="""
# 4.咨询目标
根据以上的评估和诊断，确定如下咨询目标：

1）具体目标：缓解焦虑情绪，尤其是舞台焦虑，改善睡眠状况。

2）近期目标：调整认知和心态，客观地认识自我，学会放松和现实检验。

3）长期目标和最终目标：增强心理韧性，促进心理健康发展。

# 5.咨询方案
# （一）咨询原理和方法：系统脱敏疗法
系统脱敏疗法用于逐级暴露与放松训练，并结合认知行为技术。

具体程序：

1．学习放松技巧
先学习肌肉放松与呼吸放松。

2．建构焦虑等级
再建立焦虑等级表。

# (二）时间和收费
学校咨询每周两次，每次五十分钟。

# (三）双方责任、权利和义务
咨询过程中，双方需要明确责任、权利和义务。

(1）向咨询师提供与心理问题有关的真实资料;
(2）积极主动地与咨询师一起探索解决问题的方法;
(3）完成双方商定的作业。
""".strip(),
            title="Merge Short Windows",
            domain="psychology",
            dry_run=True,
        )

        by_heading = {}
        for window in result.windows:
            by_heading.setdefault(window.section_heading, []).append(window)

        self.assertEqual(1, len(by_heading["4.咨询目标"]))
        self.assertIn("长期目标和最终目标", by_heading["4.咨询目标"][0].text)
        self.assertLessEqual(len(by_heading["5.咨询方案"]), 2)
        joined = "\n".join(window.text for window in by_heading["5.咨询方案"])
        self.assertIn("系统脱敏疗法", joined)
        self.assertIn("完成双方商定的作业", joined)

    def test_long_section_is_pre_split_before_window_building(self) -> None:
        para1 = "阶段目标 " + ("A" * 4200)
        para2 = "认知重构 " + ("B" * 4200)
        para3 = "家庭作业 " + ("C" * 4200)
        record = DocumentRecord(
            doc_id="doc-long",
            source_type="markdown_document",
            title="Long Section",
            domain="psychology",
            raw_text=f"# 长章节\n\n{para1}\n\n{para2}\n\n{para3}",
            sections=[
                DocumentSection(
                    heading="长章节",
                    text=f"{para1}\n\n{para2}\n\n{para3}",
                    level=1,
                    span=TextSpan(start=0, end=len(f"{para1}\n\n{para2}\n\n{para3}")),
                    metadata={"heading_path": ["长章节"]},
                )
            ],
            content_hash="hash-long",
        )

        windows = build_windows_for_record(
            record=record,
            strategy="chunk",
            max_chars=20000,
            max_section_chars=10000,
        )

        self.assertEqual(2, len(windows))
        self.assertEqual(1, windows[0].metadata["section_chunk_index"])
        self.assertEqual(2, windows[0].metadata["section_chunk_count"])
        self.assertEqual(2, windows[1].metadata["section_chunk_count"])
        self.assertLessEqual(len(windows[0].text), 10000)
        self.assertLessEqual(len(windows[1].text), 10000)


if __name__ == "__main__":
    unittest.main()
