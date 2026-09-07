from src.dataset.base import BaseDataset
from src.dataset.llm_judge import judge_metric, judge_prompt
from typing import List, Dict, Any
import json


prompt = """Write a report of this paper in journalistic style.\n\n"""

merge_score_prompt = """You are an expert science communicator evaluating a generated popular science article.

## Source Document (Input)
{INPUT_TEXT}

## Generated Article (Output)
{GENERATED_ARTICLE}

## Reference Article (Reference)
{GOLDEN_PASSAGE}

## Independent LLM Evaluation Scores
Each score is produced by an independent LLM judge and normalized to 0.00-1.00, where higher is better. Use the descriptions below to interpret the scores; they are supporting signals, not traditional metric measurements.

1. Semantic preservation and reference coverage: {SEMANTIC_SCORE}
2. Semantic faithfulness and important-content coverage: {FAITHFULNESS_SCORE}
3. Readability and accessibility for a general audience: {READABILITY_SCORE}
4. Suitability of sentence complexity for a general audience: {COMPLEXITY_SCORE}
5. Familiarity and clarity of language: {LANGUAGE_SCORE}

## Task
Give one holistic score from 0 to 10 for factual accuracy, faithfulness, coherence, organization, readability, and accessibility.
Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string). Do not mention the names or numeric values of the supporting scores in the reason.
"""

class JRE_L_Dataset(BaseDataset):

    def __init__(self, data_path: str = None, dataset_name: str = "JRE-L", test_metrics: List[str] = ["llm_judge_score"], max_output_len: int = 8192, eval_mode: bool = True):
        self.dataset_name = dataset_name
        # self.feedback_type = feedback_type
        super().__init__(data_path=data_path, test_metrics=test_metrics, max_output_len=max_output_len)
        

    # def _load_data(self) -> Dict[str, List[Dict[str, Any]]]:
        # max_len = 1024
        # raw_data = []
        # len_ = 0
        # with jsonlines.open(self.data_path) as reader:
        #     for idx, obj in enumerate(reader):
        #         raw_data.append({
        #             "test_idx": len_,
        #             "input_prompt": prompt + f"""### Meta Info\nTitle: {obj['sc-title']}\n### Content\n{" ".join(obj['sc-abstract'].split(" ")[0:max_len])}""",
        #             "dataset_name": self.dataset_name,
        #             # "feedback_type": self.feedback_type,
        #             "lang": "en",
        #             "info": {
        #                 'sc-title': obj['sc-title'],
        #                 'sc-abstract': obj['sc-abstract'],
        #                 'pr-title': obj['pr-title'],
        #                 'pr-abstract': obj['pr-summary'],
        #             }
        #         })
        #         len_ += 1
        # return raw_data

    def evaluate_single(self, user_prompt: str, info: Dict[str, Any], llm_response: str) -> Dict[str, float]:
        reference = info['pr-abstract']
        rubrics = {
            'Rouge-L': (
                'Evaluate semantic preservation and content coverage against the reference article. '
                'Consider whether the generated article retains the important facts, claims, and '
                'overall meaning of the reference, even when the wording and sentence order differ. '
                'A higher score means better preservation and coverage.'
            ),
            'BERTScore-F1': (
                'Evaluate semantic similarity and factual faithfulness to the reference article. '
                'Focus on whether the generated article expresses the same core concepts and '
                'meaning, allowing different wording, while penalizing missing, distorted, or '
                'unsupported content. A higher score means stronger semantic alignment.'
            ),
            'CLI': (
                'Evaluate readability and accessibility for a general, non-specialist audience. '
                'Prefer clear popular-science prose that explains technical ideas without requiring '
                'advanced education, uses manageable sentence structures, and is not unnecessarily '
                'dense. Treat a grade level around 8-12 as generally suitable, while considering '
                'the actual clarity and audience fit rather than applying a mechanical cutoff. '
                'A higher score means more accessible writing.'
            ),
            'FKGL': (
                'Evaluate whether the article uses a sentence and vocabulary complexity appropriate '
                'for a general reader. Prefer prose that can be understood without specialized '
                'training; a grade level around 8-12 is generally suitable for popular science. '
                'Do not reward complexity for its own sake. A higher score means the article is '
                'clearer and better suited to the intended audience.'
            ),
            'DCRS': (
                'Evaluate the familiarity and accessibility of the language. Prefer commonly '
                'understood words, concise explanations, and clear wording, while allowing '
                'necessary scientific terms when they are explained in context. Penalize obscure '
                'wording, unexplained jargon, and prose that is difficult for a general audience. '
                'A higher score means the article is easier to understand.'
            ),
        }
        intermediate_scores = []
        for metric, rubric in rubrics.items():
            result = judge_metric(self.dataset_name, metric, user_prompt, llm_response, reference, rubric)
            intermediate_scores.append(result['llm_judge_score'] / 10.0)
        final_prompt = merge_score_prompt.format(
            INPUT_TEXT=user_prompt,
            GENERATED_ARTICLE=llm_response,
            GOLDEN_PASSAGE=reference,
            SEMANTIC_SCORE=f"{intermediate_scores[0]:.4f}",
            FAITHFULNESS_SCORE=f"{intermediate_scores[1]:.4f}",
            READABILITY_SCORE=f"{intermediate_scores[2]:.4f}",
            COMPLEXITY_SCORE=f"{intermediate_scores[3]:.4f}",
            LANGUAGE_SCORE=f"{intermediate_scores[4]:.4f}",
        )
        final = judge_prompt(self.dataset_name, final_prompt)
        return {"llm_judge_score": final["llm_judge_score"] / 10.0}
        
if __name__ == "__main__":
    # Example usage
    dataset = JRE_L_Dataset(data_path="./raw/JRE-L/test.json")
    
    item = dataset.get_data(9)
    
    print(">>>>> JRE_L Dataset Length:", len(dataset))
    
    print(">>>>> Item:")
    
    print(json.dumps(item, ensure_ascii=False, indent=2))
    
    print(">>>>> Evaluation Score:")
    
    score = dataset.evaluate([{
        "test_idx": 9,
        "response": """This is a paper.""",
    }])
    
    print(json.dumps(score, ensure_ascii=False, indent=2))
