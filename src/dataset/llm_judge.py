"""Shared LLM-as-a-judge helpers for MemoryBench datasets."""

import json
import os
import re
from typing import Any, Dict

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env"))

def build_judge_prompt(dataset: str, user_prompt: Any, response: Any,
                       info: Dict[str, Any], rubric: str) -> str:
    reference = info.get("golden_answer", info.get("abstract", info.get("ground_truth", "")))
    return f"""You are the official evaluator for the MemoryBench dataset {dataset}.
Return ONLY valid JSON with exactly two keys: score (integer 0-10) and reason (string).

RUBRIC:
{rubric}

USER REQUEST:
{_compact(user_prompt)}

REFERENCE / GOLD ANSWER (may be empty):
{_compact(reference)}

ADDITIONAL ANNOTATIONS:
{_compact(info)}

MODEL RESPONSE:
{_compact(response)}
"""


def _call_api(messages: list[dict], max_tokens: int = 1024) -> str:
    """Call the configured OpenAI-compatible judge API."""
    from src.llms import LlmFactory
    client = LlmFactory.create("openai", {
        "openai_base_url": os.getenv("EVALUATE_BASE_URL"),
        "model": os.getenv("EVALUATE_MODEL", "qwen3.8-27b"),
        "api_key": os.getenv("EVALUATE_API_KEY"),
        "temperature": 0.0,
        "top_p": 0.1,
        "max_tokens": max_tokens,
    })
    return client.generate_response(
        messages,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )


def _compact(value: Any, limit: int = 12000) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return text if len(text) <= limit else text[:limit] + "\n[truncated]"


def _parse_score(raw: str) -> tuple[int, str]:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("empty judge response")
    cleaned = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I | re.M).strip()
    try:
        obj = json.loads(cleaned)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        # Some OpenAI-compatible servers still add a short preamble despite the
        # JSON-only instruction. Parse the first complete JSON object if present.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("judge response is not valid JSON") from exc
        try:
            obj = json.loads(cleaned[start:end + 1])
        except (TypeError, ValueError, json.JSONDecodeError) as nested_exc:
            raise ValueError("judge response is not valid JSON") from nested_exc
    if not isinstance(obj, dict) or "score" not in obj or "reason" not in obj:
        raise ValueError("judge JSON must contain score and reason")
    try:
        score = max(0, min(10, int(round(float(obj["score"])))) )
    except (TypeError, ValueError) as exc:
        raise ValueError("judge score must be numeric") from exc
    return score, str(obj["reason"])


def judge_one(dataset: str, user_prompt: Any, response: Any, info: Dict[str, Any],
              rubric: str) -> Dict[str, Any]:
    prompt = build_judge_prompt(dataset, user_prompt, response, info, rubric)
    last_error = ""
    for _ in range(3):
        try:
            raw = _call_api([
                {"role": "system", "content": "You are a strict, evidence-based evaluator."},
                {"role": "user", "content": prompt},
            ])
            if not raw:
                raise ValueError("judge returned empty content")
            score, reason = _parse_score(raw)
            return {
                "llm_judge_score": score,
                "judge_reason": reason,
                "judge_raw_response": str(raw),
                "judge_prompt": prompt,
            }
        except Exception as exc:  # retry transient API failures
            last_error = repr(exc)
    return {
        "llm_judge_score": 0,
        "judge_reason": "Judge API failure: " + last_error,
        "judge_raw_response": "",
        "judge_prompt": prompt,
        "judge_error": True,
    }


def judge_prompt(dataset: str, prompt: str) -> Dict[str, Any]:
    """Run a dataset-owned final judge prompt and parse its JSON score."""
    last_error = ""
    # Empty responses and malformed JSON are transient with the remote judge;
    # retry enough times that one failed request cannot become a false zero.
    for _ in range(5):
        try:
            raw = _call_api([
                {"role": "system", "content": "You are a strict, evidence-based evaluator."},
                {"role": "user", "content": prompt},
            ], max_tokens=512)
            score, reason = _parse_score(raw)
            return {
                "llm_judge_score": score,
                "judge_reason": reason,
                "judge_raw_response": str(raw),
                "judge_prompt": prompt,
            }
        except Exception as exc:
            last_error = repr(exc)
    return {
        "llm_judge_score": 0,
        "judge_reason": "Judge API failure: " + last_error,
        "judge_raw_response": "",
        "judge_prompt": prompt,
        "judge_error": True,
    }


def judge_metric(dataset: str, metric: str, user_prompt: Any, response: Any,
                 reference: Any, rubric: str) -> Dict[str, Any]:
    """Score one legacy metric through a dataset-owned metric rubric.

    This is deliberately a thin helper. Dataset classes choose the metric
    names, wording, and number of calls; the base evaluator does not know
    about this protocol.
    """
    return judge_one(
        dataset,
        user_prompt,
        response,
        {"golden_answer": reference, "metric": metric},
        rubric=(
            f"Evaluate only the metric '{metric}'. Return an integer score from 0 to 10.\n"
            f"{rubric}\n"
            "Do not score writing style unless it is part of this metric."
        ),
    )
