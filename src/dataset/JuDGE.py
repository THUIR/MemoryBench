from src.dataset.base import BaseDataset
from typing import List, Dict, Any
import json
from src.dataset.llm_judge import judge_metric, judge_prompt

merge_score_prompt = """You are the final, strict evaluator for the Chinese criminal-judgment task JuDGE.
Evaluate the generated judgment against the reference judgment for the same case. The reference
judgment is the authority for the expected disposition. Do not reward length, formal headings,
fluent Chinese, or plausible legal boilerplate when the legally material result is wrong.

## Case Facts (Input)
{INPUT_FACTS}

## Generated Judgment (Output)
{GENERATED_JUDGMENT}

## Reference Judgment
{GOLDEN_JUDGMENT}

## Independent LLM Evaluation Scores
Each score is an independent supporting signal in [0, 1]. Treat these scores as evidence, not
as a substitute for checking the two documents. In particular, semantic similarity and reasoning
quality must not compensate for an incorrect charge, statute, sentence, or fine.

1. Coverage of the reference reasoning: {S1}
2. Agreement with the reference legal conclusions: {S2}
3. Faithfulness and completeness of the reasoning: {S3}
4. Faithfulness and completeness of the judgment result: {S4}
5. Coverage of reference crimes and charges: {S5}
6. Legal support and absence of invented crimes or charges: {S6}
7. Combined correctness and coverage of crimes and charges: {S7}
8. Coverage of reference statutory citations: {S8}
9. Correctness of cited statutory provisions: {S9}
10. Combined correctness and coverage of statutory citations: {S10}
11. Accuracy of the prison sentence duration: {S11}
12. Accuracy of the monetary fine amount: {S12}

## Required checking procedure
1. Compare the reference and generated disposition line by line. Identify every material expected
   charge/crime, acquittal or non-conviction, statutory article, prison/custodial term, suspended
   term, fine, and other explicitly ordered monetary consequence.
2. Check whether the generated judgment states the same result. A missing material item is an error;
   an invented crime, statute, sentence, or fine is also an error. Do not infer a value merely because
   it is common for similar cases. If the reference does not state a value, do not penalize the output
   for omitting that value.
3. Check that the reasoning supports the result and does not contradict the case facts or reference.
   Treat unsupported factual additions as errors, but do not require identical names, dates, docket
   numbers, or boilerplate when they are not material to the legal result.
4. Assign the score using these anchors: 10 = all material results and reasoning correct; 8 = only
   minor non-material omissions or wording issues; 6 = broadly correct result but one material
   omission or a noticeable reasoning/statute error; 4 = mixed result with a material wrong charge,
   statute, sentence, or fine; 2 = several material errors or a substantially wrong disposition;
   0 = unusable, contradictory, or no meaningful judgment. Scores between anchors are allowed only
   when the case genuinely falls between them.
5. Apply this ceiling rule: if any principal crime/charge is wrong or missing, or if a clearly stated
   reference sentence or fine is materially wrong, the final score cannot exceed 6; if two or more
   such decisive fields are wrong, it cannot exceed 4. A merely stylistic difference is never a
   decisive error. Do not mechanically average the supporting scores.

Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string). In the reason,
briefly name the decisive matching or mismatching legal fields. Do not mention the supporting score
labels or their numeric values.
"""


    
class JuDGE_Dataset(BaseDataset):

    def __init__(self, data_path: str = None, dataset_name: str = "JuDGE", test_metrics: List[str] = ["llm_judge_score"], max_output_len: int = 8192, eval_mode: bool = True):
        # self.evaluate_threads = 4
        self.dataset_name = dataset_name
        # self.feedback_type = feedback_type
        super().__init__(data_path=data_path, test_metrics=test_metrics, max_output_len=max_output_len)
#     def _load_data(self) -> Dict[str, List[Dict[str, Any]]]:
#         raw_data = []
#         len_ = 0
        
#         for t in ["train", "test"]:
#             with jsonlines.open(os.path.join(self.data_path, f"{t}.json")) as reader:
#                 for idx, obj in enumerate(reader):
#                     exp_ans = obj['fd']
#                     fact = obj['text']
#                     input_content = f"""
# 案件事实：{fact}
# 请根据上面提供的事实描述，生成一篇完整且具有法律效力的中文的刑事判决书。生成的文书必须结构严谨、逻辑清晰；确保文书所有部分均符合真实司法文书的写作规范，语言应正式、客观、清晰
# """
#                     messages = [
#                         {"role": "system", "content": "你是一个法律助理，提供帮助。"},
#                         {"role": "user", "content": input_content}
#                     ]
#                     raw_data.append({
#                         "test_idx": len_,
#                         "input_chat_messages": messages,
#                         "dataset_name": self.dataset_name,
#                         # "feedback_type": self.feedback_type,
#                         "lang": "zh",
#                         "info": {
#                             'golden_answer': exp_ans,
#                         }
#                     })
#                     len_ += 1
#         return raw_data

    def evaluate_single(self, user_prompt: str, info: Dict[str, Any], llm_response: str) -> Dict[str, float]:
        rubrics = {
            "reasoning_meteor": "Compare the reasoning's material propositions with the reference. Score coverage of the reference's legal analysis and whether each conclusion is supported. Ignore shared boilerplate and surface word overlap. Penalize a missing dispositive issue or a contradiction.",
            "judge_meteor": "Compare only the operative legal result, not wording. Check every conviction/acquittal, charge, sentence, suspension, fine, and other explicit order against the reference. Missing or invented material results are errors; use conservative scoring when a result is ambiguous.",
            "reasoning_bert_score": "Assess semantic faithfulness of the reasoning to the case facts and reference. Reward correct issue identification, legally supported application, and complete treatment of material facts. Do not reward generic legal prose or length.",
            "judge_bert_score": "Assess semantic faithfulness of the operative judgment result to the reference. Give high scores only when the material disposition matches, including charges, non-convictions, statutes when stated, and sentence/fine terms. A fluent but legally different disposition must score low.",
            "crime_recall": "Extract the reference's complete set of material crimes/charges and dispositions, including charges the reference rejects when that rejection is part of the result. Score coverage: 10 means all are correctly represented, 5 means roughly half or materially incomplete, 0 means none. Do not count generic labels or unsupported allegations as correct coverage.",
            "crime_precision": "Extract every crime/charge that the generated judgment treats as established or imposed. Score whether each is supported by the reference disposition and case facts. Penalize invented convictions, omitted acquittals presented as convictions, and conflated distinct offenses. Do not penalize harmless boilerplate.",
            "crime_f1": "Jointly evaluate crime/disposition coverage and correctness. First identify the reference set and generated set, then balance missing material crimes against invented or wrongly affirmed crimes. Use 10 only for complete and correct agreement.",
            "penalcode_index_recall": "Compare the statutory articles that are material to the reference's final reasoning and disposition. Score coverage of those article numbers and their relevant paragraph/item when specified. Do not require copying an article that is absent from the reference.",
            "penalcode_index_precision": "Check every statutory article and paragraph relied on in the generated judgment against the reference and the stated legal conclusion. Penalize wrong, irrelevant, or invented citations; correct citation formatting alone is not enough.",
            "penalcode_index_f1": "Jointly evaluate recall and precision of material statutory citations. Missing a decisive article and citing a wrong article are both material errors. Ignore articles copied only in an unrelied-on boilerplate appendix unless the reference treats them as part of the result.",
            "time_score": "Extract all reference custodial terms, prison terms, detention terms, and suspension/probation terms. Compare numbers and units, including combined sentences. Score 10 only when every stated material term matches; a materially different duration or missing suspension is a serious error. If the reference states no term, score based on not inventing one.",
            "amount_score": "Extract every reference fine or other explicit monetary order and compare amount, currency, and whether it is imposed. Score 10 only when each stated amount and its imposed/waived status matches. A materially wrong or invented fine is a serious error; if the reference states no monetary amount, do not invent a penalty for omission.",
        }
        intermediate_scores = []
        for metric, rubric in rubrics.items():
            result = judge_metric(self.dataset_name, metric, user_prompt, llm_response, info['golden_answer'], rubric)
            intermediate_scores.append(result['llm_judge_score'] / 10.0)
        final_prompt = merge_score_prompt.format(
            INPUT_FACTS=user_prompt,
            GENERATED_JUDGMENT=llm_response,
            GOLDEN_JUDGMENT=info['golden_answer'],
            **{f"S{i}": f"{score:.4f}" for i, score in enumerate(intermediate_scores, 1)},
        )
        final = judge_prompt(self.dataset_name, final_prompt)
        return {"llm_judge_score": final["llm_judge_score"] / 10.0}
    
    
if __name__ == "__main__":
    # Example usage
    dataset = JuDGE_Dataset(data_path="./raw/JuDGE")
    
    item = dataset.get_data(9)
    
    print(">>>>> JuDGE Dataset Length:", len(dataset))
    
    print(">>>>> Item:")
    
    print(json.dumps(item, ensure_ascii=False, indent=2))
    
    print(">>>>> Evaluation Score:")
    
    score = dataset.evaluate_and_summary([{
        "test_idx": 9,
        "response": dataset.get_data(9)['info']['golden_answer'],
    }])
    
    import time
    start = time.time()
    
    print(">>>>> Evaluation Score:")
    
    score = dataset.evaluate_and_summary([{
        "test_idx": 9,
        "response": dataset.get_data(9)['info']['golden_answer'],
    }])
    
    print(json.dumps(score, ensure_ascii=False, indent=2))
    
    print("Total Time:", time.time() - start)
    
    
    # print(">>>>> Evaluation Test Score:")
    
    # score = dataset.evaluate_test([{
    #     "test_idx": 9,
    #     "response": dataset.get_data(9)['info']['golden_answer'],
    # }])
    
    # print(json.dumps(score, ensure_ascii=False, indent=2))
