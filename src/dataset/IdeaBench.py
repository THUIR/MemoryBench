import os
import json
import re
import random
from typing import List, Dict, Any

from src.dataset.base import BaseDataset
from src.llms import LlmFactory
from src.dataset.llm_judge import judge_metric, judge_prompt

from pydantic import BaseModel, Field



def extract_info(pattern, text):
    if not isinstance(text, str):
        return None
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1)
    else:
        return None


IDEA_SEPARATOR = "---IDEA-SEPARATOR---"

GENERATION_PROMPT_PREFIX = """You are a biomedical researcher. You are tasked with creating novel hypotheses or research ideas given some background knowledge. The background knowledge I will provide are abstracts from other papers.

Here are the abstracts:"""

GENERATION_PROMPT_SUFFIX = f"""Using these abstracts, reason over them and come up with 3 novel and distinct hypotheses. Please avoid copying ideas directly, rather use the insights to inspire novel hypotheses.
Format each hypothesis as a brief and concise paragraph.
IMPORTANT: Separate the 3 hypotheses with '{IDEA_SEPARATOR}'."""


RATING_PROMPT_TEMPLATE = """You are an expert in understanding and analyzing scientific content. Your task is to evaluate the strongest meaningful overlap between the generated hypotheses and the abstract of a scientific paper. Consider every generated hypothesis and do not give preference based on its position. Then, rate the best-supported overlap on a scale of 1 to 10, where 1 indicates minimal or no overlap, and 10 indicates a perfect or nearly perfect overlap. Provide a brief explanation for your rating.

Your output MUST be a JSON object with two keys: "rating" (integer 1-10) and "explanation" (string).

<GeneratedHypotheses>
{hypotheses}
</GeneratedHypotheses>

<Abstract>
{abstract}
</Abstract>
"""

RANKING_PROMPT_PREFIX = """You are a reviewer tasked with ranking the quality of a set of research ideas based on their {ranking_criteria}. The idea with the highest {ranking_criteria} should be ranked first. 

Please rank the following hypotheses. Your output should be a numbered list, starting with the best idea. For example:
1. **Hypothesis C**: (brief rationale)
2. **Hypothesis A**: (brief rationale)
...

You must include every candidate exactly once. Use only the candidate labels
shown below (for example, A, B, C, D). Do not invent labels or omit labels.

Here are the hypotheses to rank:
"""

SHORT_SEMANTIC_ALIGNMENT_PROMPT = """You are evaluating semantic alignment for IdeaBench.
Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string).
Compare the generated research hypotheses with the reference abstract. Score only
meaning preservation, scientific topic alignment, and coverage; do not reward
surface wording or general fluency.

REFERENCE ABSTRACT:
{reference}

GENERATED HYPOTHESES:
{generated}
"""

merge_score_prompt = """You are an expert scientific researcher and AI assistant. Your task is to evaluate the overall quality of an automatically generated research idea based on the provided context and a set of independent LLM-based evaluation scores.

## Background Knowledge (Input)
{INPUT_CONTEXT}

## Generated Research Idea (Output)
{GENERATED_IDEA}

## Ground Truth Research Idea (Reference)
{GOLDEN_IDEA}

## Evaluation Scores
Below are scores produced by separate LLM judges. Every score is normalized to the range 0.00 to 1.00, where a higher score is better. Each description defines what that judge evaluated. These are supporting signals, not ground-truth measurements.

1. Semantic Alignment and Coverage: Measures how well the generated research ideas preserve the meaning, important content, and scientific concepts of the reference idea. Surface wording differences should not be penalized.
semantic_alignment_score: {SEMANTIC_ALIGNMENT_SCORE}

2. Meaningful Idea Overlap: Measures how meaningfully the generated idea overlaps with the reference idea, considering relevance, correspondence of the proposed research direction, and substantive alignment.
idea_overlap_score: {IDEA_OVERLAP_SCORE}

3. Novelty: Measures the originality and distinctiveness of the generated ideas relative to the reference idea and the provided background knowledge. A higher score means stronger useful novelty.
novelty_score: {NOVELTY_SCORE}

4. Feasibility: Measures whether the generated ideas are scientifically plausible, implementable, and supported by a credible research plan. A higher score means stronger feasibility.
feasibility_score: {FEASIBILITY_SCORE}

## Task
Based on the input, generated ideas, reference idea, and the evaluation scores, provide one holistic score from 0 to 10 for the overall quality of the generated research idea.
- 0: Completely irrelevant, incoherent, or unusable.
- 10: Scientifically relevant, insightful, novel, feasible, coherent, and well aligned with the research context.

Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string). Do not mention the names or numeric values of the independent evaluation scores in the reason.
"""

COMPACT_MERGE_SCORE_PROMPT = """You are the final evaluator for the IdeaBench research-idea task.
Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string).

Evaluate the generated research ideas against the reference abstract. Consider:
scientific relevance, substantive alignment, novelty, feasibility, coherence, and
whether the response proposes usable research hypotheses. Do not require lexical
overlap. A response that is fluent but scientifically unrelated must score low.

REFERENCE ABSTRACT:
{GOLDEN_IDEA}

GENERATED IDEAS:
{GENERATED_IDEA}

SUPPORTING SCORES:
semantic alignment: {SEMANTIC_ALIGNMENT_SCORE}
idea overlap: {IDEA_OVERLAP_SCORE}
novelty: {NOVELTY_SCORE}
feasibility: {FEASIBILITY_SCORE}

Return the JSON object now.
"""

class BaseAgentConfig(BaseModel):
    llm_provider: str = Field(
        default="openai", 
        description="The LLM provider to use for the agent."
    )
    llm_config: dict = Field(
        default_factory=dict, 
        description="Configuration parameters for the LLM."
    )
    

class IdeaBench_Dataset(BaseDataset):

    def __init__(self, data_path: str = "", num_ref: int = 3, all_ref: bool = False, test_metrics: List[str] = ['llm_judge_score'], max_output_len: int = 8192, eval_mode: bool = True) -> None:
        """
        初始化 IdeaBench 数据集

        Args:
            num_ref (int): 生成时用作背景知识的参考文献摘要数量
            all_ref (bool): 是否使用所有参考文献
        """
        self.dataset_name = "IdeaBench"
        self.evaluate_threads = 4
        self.target_papers_path = os.path.join(data_path, 'target_papers.csv')
        self.references_path = os.path.join(data_path, 'filtered_references.csv')
        self.num_ref = num_ref
        self.all_ref = all_ref
        # self.feedback_type = feedback_type
        super().__init__(data_path, test_metrics, max_output_len=max_output_len)

        
        config = BaseAgentConfig(
            llm_config = {
                "openai_base_url": os.getenv("EVALUATE_BASE_URL"),
                "model": os.getenv("EVALUATE_MODEL"),
                "api_key": os.getenv("EVALUATE_API_KEY"),
                "temperature": 0.0,
                "max_tokens": 1024,
            }
        )
        
        self.openai_model = LlmFactory.create(
            provider_name=config.llm_provider,
            config=config.llm_config,
        )
        

    # def _load_data(self) -> List[Dict[str, Any]]:
    #     """
    #     从 CSV 文件加载数据并构建生成 Prompt
    #     """

    #     target_df = pd.read_csv(self.target_papers_path)
    #     ref_df = pd.read_csv(self.references_path).dropna(subset=['abstract'])
        
    #     dataset = []
    #     for idx, row in tqdm(target_df.iterrows(), total=len(target_df), desc="Preparing prompts"):
    #         target_paper_id = row['paperId']
            
    #         ref_abstracts_all = ref_df[ref_df['targetPaperId'] == target_paper_id]['abstract'].tolist()
            
    #         if self.all_ref:
    #             selected_refs = ref_abstracts_all
    #         else:
    #             n_samples = min(self.num_ref, len(ref_abstracts_all))
    #             selected_refs = random.sample(ref_abstracts_all, n_samples)
            
    #         background_knowledge = []
    #         for i, abstract in enumerate(selected_refs):
    #             clean_abstract = abstract.replace("{greater than or equal to}", "≥").replace("{", "").replace("}", "")
    #             background_knowledge.append(f"Abstract {i+1}: {clean_abstract}")
            
    #         background_text = "\n\n".join(background_knowledge)

    #         input_prompt = f"{GENERATION_PROMPT_PREFIX}\n\n{background_text}\n\n{GENERATION_PROMPT_SUFFIX}"
            
    #         dataset.append({
    #             "test_idx": idx,
    #             "input_prompt": input_prompt,
    #             "dataset_name": "IdeaBench",
    #             "lang": "en",
    #             "info": {
    #                 "paperId": target_paper_id,
    #                 "title": row['title'],
    #                 "abstract": row['abstract']
    #             },
    #             # "feedback_type": self.feedback_type
    #         })
    #     print(f"Data loading complete. {len(dataset)} items loaded.")
    #     return dataset

    def _get_llm_rating(self, hypotheses: str, abstract: str) -> Dict:
        """使用 LLM 对全部 hypotheses 与 abstract 的最佳重叠度进行打分"""
        prompt = RATING_PROMPT_TEMPLATE.format(hypotheses=hypotheses, abstract=abstract)
        messages = [{'role': 'user', 'content': prompt}]
        
        last_response = None
        for _ in range(3):
            try:
                last_response = self.openai_model.generate_response(
                    messages,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
            except Exception as exc:
                last_response = f"API error: {exc}"
                continue
            response_str = last_response if isinstance(last_response, str) else str(last_response or "")
            if '```json' in response_str:
                response_str = extract_info(r'```json\s*(.*?)\s*```', response_str) or response_str
            try:
                result = self._parse_json_object(response_str)
                rating = int(result.get("rating"))
                if 1 <= rating <= 10:
                    return {"rating": rating, "explanation": str(result.get("explanation", ""))}
            except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
                pass
        print(f"Warning: Could not parse LLM rating response as JSON. Response: {last_response}")
        return {"rating": 0, "explanation": str(last_response or ""), "judge_error": True}

    def _get_llm_ranking(self, hypotheses: List[str], abstract: str, criteria: str) -> Dict:
        """使用 LLM 对一组 ideas (包括 ground truth) 进行排序"""
        # IdeaBench only uses the reference idea's position. Asking for that
        # position directly is much more reliable than asking the endpoint to
        # generate a long, formatted permutation.
        candidates = [f"A: {self._compact_text(abstract, 350)}"]
        for i, hyp in enumerate(hypotheses):
            letter = chr(ord('A') + i + 1)
            candidates.append(f"{letter}: {self._compact_text(hyp, 350)}")
        
        
        candidates_text = "\n\n".join(candidates)
        prompt = (
            f"Rank these {len(hypotheses) + 1} research ideas by {criteria}, highest first.\n"
            "Candidate A is the reference idea. What position should candidate A have?\n"
            f"Return ONLY JSON: {{\"rank\": integer from 1 to {len(hypotheses) + 1}, \"reason\": \"short\"}}.\n\n"
            f"{candidates_text}"
        )
        messages = [{'role': 'user', 'content': prompt}]
        
        last_response = None
        for _ in range(3):
            try:
                last_response = self.openai_model.generate_response(
                    messages,
                    max_tokens=128,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                )
            except Exception as exc:
                last_response = f"API error: {exc}"
                continue
            response_str = last_response if isinstance(last_response, str) else str(last_response or "")
            rank = self._parse_target_rank(response_str, len(hypotheses) + 1)
            if rank is not None:
                return {"r_target": rank, "ranking": ["A"], "raw_text": response_str}
        print(f"Warning: Could not parse valid {criteria} ranking. Response: {last_response}")
        return {"r_target": 0, "ranking": [], "raw_text": str(last_response or ""), "judge_error": True}

    @staticmethod
    def _parse_target_rank(response: str, size: int) -> int | None:
        if not isinstance(response, str):
            return None
        text = response.strip()
        try:
            obj = IdeaBench_Dataset._parse_json_object(text)
            value = int(obj.get("rank"))
            if 1 <= value <= size:
                return value
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        if text.isdigit() and 1 <= int(text) <= size:
            return int(text)
        return None

    @staticmethod
    def _parse_ranking_labels(response: str, expected: set[str]) -> List[str] | None:
        """Extract the first complete ranking when a model repeats its answer."""
        if not isinstance(response, str):
            return None
        # Preferred compact format: ``A,B,C,D``. Restrict this to a line made
        # solely of labels so letters in the rationale cannot be mistaken for
        # ranking positions.
        size = len(expected)
        for line in response.splitlines():
            compact = [part.strip().upper() for part in re.split(r"[,;>\s]+", line.strip()) if part.strip()]
            if len(compact) == size and set(compact) == expected and len(set(compact)) == size:
                return compact

        labels = [label.upper() for label in re.findall(
            r"(?:^|\n)\s*(?:\d+\s*[.)-]?\s*)?(?:\*\*)?\s*Hypothesis\s*\(?\s*([A-Z])\s*\)?\b",
            response,
            flags=re.IGNORECASE,
        )]
        for start in range(max(0, len(labels) - size + 1)):
            candidate = labels[start:start + size]
            if len(candidate) == size and set(candidate) == expected and len(set(candidate)) == size:
                return candidate

        # Also accept inline labels such as "Hypothesis A" when the model
        # ignores the requested numbered-list format. Still require a complete
        # permutation so prose cannot silently become a ranking.
        labels = [label.upper() for label in re.findall(
            r"\bHypothesis\s*\(?\s*([A-Z])\s*\)?\b", response, flags=re.IGNORECASE
        )]
        for start in range(max(0, len(labels) - size + 1)):
            candidate = labels[start:start + size]
            if len(candidate) == size and set(candidate) == expected and len(set(candidate)) == size:
                return candidate
        return None

    @staticmethod
    def _parse_json_object(response: str) -> Dict[str, Any]:
        text = str(response or "").strip()
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("rating response is not valid JSON")
            fragment = text[start:end + 1]
            try:
                value = json.loads(fragment)
            except json.JSONDecodeError:
                # Qwen occasionally leaves a trailing comma before the close.
                value = json.loads(re.sub(r",\s*([}\]])", r"\1", fragment))
        if not isinstance(value, dict):
            raise ValueError("rating response must be a JSON object")
        return value


    def evaluate_single(self, user_prompt: str, info: Dict[str, Any], llm_response: str) -> Dict[str, Any]:

        hypotheses = [h.strip() for h in llm_response.split(IDEA_SEPARATOR) if h.strip()]
        if len(hypotheses) < 3:
            # 补齐到 3 个 hypothesis
            hypotheses += ["NULL"] * (3 - len(hypotheses))
        hypotheses = sorted(hypotheses)
        hypotheses_text = "\n\n".join(
            f"Hypothesis {index}: {hypothesis}"
            for index, hypothesis in enumerate(hypotheses, start=1)
        )
        
        ground_truth_abstract = info['abstract']
        
        semantic_prompt = SHORT_SEMANTIC_ALIGNMENT_PROMPT.format(
            reference=self._compact_text(ground_truth_abstract, 700),
            generated=self._compact_text(hypotheses_text, 700),
        )
        bert_result = judge_prompt(self.dataset_name, semantic_prompt)
        bert_scores_f1 = bert_result["llm_judge_score"] / 10.0
        

        llm_rating = self._get_llm_rating(hypotheses_text, ground_truth_abstract)
        
        llm_novelty_ranking = self._get_llm_ranking(hypotheses, ground_truth_abstract, "novelty")
        llm_feasibility_ranking = self._get_llm_ranking(hypotheses, ground_truth_abstract, "feasibility")

        llm_rating_score = llm_rating.get("rating", 0) or 0
        llm_novelty_ranking_score = self._ranking_score(llm_novelty_ranking["r_target"], len(hypotheses))
        llm_feasibility_ranking_score = self._ranking_score(llm_feasibility_ranking["r_target"], len(hypotheses))
        final_prompt = merge_score_prompt.format(
            INPUT_CONTEXT=user_prompt,
            GENERATED_IDEA=hypotheses_text,
            GOLDEN_IDEA=ground_truth_abstract,
            SEMANTIC_ALIGNMENT_SCORE=f"{bert_scores_f1:.4f}",
            IDEA_OVERLAP_SCORE=f"{llm_rating_score / 10.0:.4f}",
            NOVELTY_SCORE=f"{llm_novelty_ranking_score:.4f}",
            FEASIBILITY_SCORE=f"{llm_feasibility_ranking_score:.4f}",
        )
        final = judge_prompt(self.dataset_name, final_prompt)
        if final.get("judge_error"):
            # The full merge prompt contains all three source abstracts and can
            # exceed the remote judge's reliable request size. Retry with the
            # information needed for the final decision only.
            compact_prompt = COMPACT_MERGE_SCORE_PROMPT.format(
                # This endpoint occasionally returns content=null for longer
                # judge prompts. Keep the retry well below that request-size
                # boundary while retaining enough scientific context.
                GOLDEN_IDEA=self._compact_text(ground_truth_abstract, 900),
                GENERATED_IDEA=self._compact_text(hypotheses_text, 900),
                SEMANTIC_ALIGNMENT_SCORE=f"{bert_scores_f1:.4f}",
                IDEA_OVERLAP_SCORE=f"{llm_rating_score / 10.0:.4f}",
                NOVELTY_SCORE=f"{llm_novelty_ranking_score:.4f}",
                FEASIBILITY_SCORE=f"{llm_feasibility_ranking_score:.4f}",
            )
            final = judge_prompt(self.dataset_name, compact_prompt)
        return {
            "llm_judge_score": final["llm_judge_score"] / 10.0,
            "judge_error": bool(
                llm_rating.get("judge_error")
                or llm_novelty_ranking.get("judge_error")
                or llm_feasibility_ranking.get("judge_error")
                or final.get("judge_error")
            ),
            "semantic_alignment_error": bool(bert_result.get("judge_error")),
            "rating_error": bool(llm_rating.get("judge_error")),
            "novelty_ranking_error": bool(llm_novelty_ranking.get("judge_error")),
            "feasibility_ranking_error": bool(llm_feasibility_ranking.get("judge_error")),
            "merge_error": bool(final.get("judge_error")),
            "idea_rating": llm_rating.get("rating", 0),
            "idea_novelty_rank": llm_novelty_ranking.get("r_target", 0),
            "idea_feasibility_rank": llm_feasibility_ranking.get("r_target", 0),
            "idea_novelty_ranking": llm_novelty_ranking.get("ranking", []),
            "idea_feasibility_ranking": llm_feasibility_ranking.get("ranking", []),
        }

    @staticmethod
    def _ranking_score(rank: int, hypothesis_count: int) -> float:
        if rank <= 0 or hypothesis_count <= 0:
            return 0.0
        return (rank - 1) / hypothesis_count

    @staticmethod
    def _compact_text(value: Any, limit: int) -> str:
        text = value if isinstance(value, str) else str(value or "")
        return text if len(text) <= limit else text[:limit] + "\n[truncated]"

if __name__ == "__main__":

    dataset = IdeaBench_Dataset(
        data_path='./raw/IdeaBench',
        num_ref=3,
        all_ref=False)
    
    print(f"\n>>>>> IdeaBench Dataset initialized. Total items: {len(dataset)}")
    

    sample_item = dataset.get_data(0)
    print("\n>>>>> Sample Item (test_idx=0):")
    print(json.dumps(sample_item, indent=2))

    print(f"\n>>>>> Generating 3 ideas...")
    generation_messages = [{'role': 'user', 'content': sample_item['input_prompt']}]
    generated_response = dataset.openai_model.generate_response(generation_messages)
    
    print("\n>>>>> Raw response from generation model:")
    print(generated_response)
    
    # 4. 使用评估流程评估生成的响应
    print(f"\n>>>>> Evaluating the response with...")
    evaluation_result = dataset.evaluate_single(
        user_prompt=sample_item['input_prompt'],
        info=sample_item['info'],
        llm_response=generated_response
    )
    
    print("\n>>>>> COMPLETE EVALUATION RESULT:")
    print(json.dumps(evaluation_result, indent=2))
    
