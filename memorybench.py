import importlib
import json
import os
from typing import Dict, List, Literal

from dotenv import load_dotenv
from tqdm import tqdm

from src.dataset.base import BaseDataset


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(CURRENT_DIR, ".env"))

os.environ.setdefault("TQDM_ASCII", "1")
os.environ.setdefault("TQDM_DYNAMIC_NCOLS", "0")
os.environ.setdefault("TQDM_NCOLS", "80")


# -------------------------------------------- Loading Datasets ----------------------------------------------

def get_dataset_class(class_path):
    module_path, class_name = class_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def load_single_dataset(dataset_name, eval_mode: bool = True) -> BaseDataset:
    config_path = os.path.join(CURRENT_DIR, "configs/datasets/each.json")
    assert os.path.exists(config_path), "configs/datasets/each.json not found"
    with open(config_path, "r") as fin:
        config = json.load(fin)
    if dataset_name not in config:
        raise ValueError(f"{dataset_name} not found, please choose from {config.keys()}")

    dataset_config = config[dataset_name].copy()
    dataset_class = get_dataset_class(f"src.dataset.{dataset_config['class_name']}")
    for key in list(dataset_config):
        if key not in dataset_class.__init__.__code__.co_varnames:
            del dataset_config[key]
    dataset_config["eval_mode"] = eval_mode
    return dataset_class(**dataset_config)


def _load_domain_or_task(name, config_file, eval_mode: bool = False) -> List[BaseDataset]:
    assert os.path.exists(config_file), f"{config_file} not found"
    with open(config_file, "r") as fin:
        configs = json.load(fin)
    assert name in configs, f"{name} not found in {config_file}, please choose from {configs.keys()}"

    dataset_list = []
    for config in configs[name]:
        dataset_config = config.copy()
        dataset_class = get_dataset_class(f"src.dataset.{dataset_config['class_name']}")
        for key in list(dataset_config):
            if key not in dataset_class.__init__.__code__.co_varnames:
                del dataset_config[key]
        dataset_config["eval_mode"] = eval_mode
        dataset_list.append(dataset_class(**dataset_config))
    return dataset_list


def load_domain(domain_name, eval_mode: bool = False) -> List[BaseDataset]:
    return _load_domain_or_task(
        domain_name, os.path.join(CURRENT_DIR, "configs/datasets/domain.json"), eval_mode
    )


def load_task(task_name, eval_mode: bool = False) -> List[BaseDataset]:
    return _load_domain_or_task(
        task_name, os.path.join(CURRENT_DIR, "configs/datasets/task.json"), eval_mode
    )


def load_memory_bench(
    dataset_type: Literal["single", "domain", "task"],
    name: str,
    eval_mode: bool = False,
) -> BaseDataset | List[BaseDataset]:
    """
    Load datasets based on the dataset type.

    Args:
        dataset_type (Literal["single", "domain", "task"]): Type of the dataset to load.
        name (str): Name of the dataset, domain, or task.
        eval_mode (bool): Whether to load the dataset in evaluation mode.

    Returns:
        If dataset_type is "single", returns a single dataset instance.
        If dataset_type is "domain" or "task", returns a list of dataset instances.
    """
    if dataset_type == "single":
        return load_single_dataset(name, eval_mode)
    if dataset_type == "domain":
        return load_domain(name, eval_mode)
    if dataset_type == "task":
        return load_task(name, eval_mode)
    raise ValueError(
        f"Unknown dataset_type {dataset_type}, please choose from ['single', 'domain', 'task']"
    )


# ------------------------------------------------ Evaluating ------------------------------------------------

def _evaluate(dataset_list: List[BaseDataset], predicts: List[Dict], on_dataset=None) -> List[Dict]:
    total_detailed_results = []
    for dataset in dataset_list:
        dataset_name = dataset.dataset_name
        print(f"=== Evaluating dataset: {dataset_name} ===")
        cur_predicts = [p for p in predicts if p["dataset"] == dataset_name]
        detailed_results = dataset.evaluate(cur_predicts)
        for result in detailed_results:
            result["dataset"] = dataset_name
            total_detailed_results.append(result)
        if on_dataset is not None and detailed_results:
            on_dataset(dataset_name, detailed_results)
    return total_detailed_results


def evaluate(
    dataset_type: Literal["single", "domain", "task"],
    name: str,
    predicts: List[Dict],
    on_dataset=None,
) -> List[Dict]:
    """
    Evaluate the predictions against the specified dataset(s).

    Args:
        dataset_type (Literal["single", "domain", "task"]): Type of the dataset to evaluate against.
        name (str): Name of the dataset, domain, or task.
        predicts (List[Dict]): List of prediction dictionaries, each containing 'test_idx', 'response', and 'dataset'.

    Returns:
        List[Dict]: List of evaluation details for each prediction.
    """
    for predict in predicts:
        assert "test_idx" in predict, "Each predict must have 'test_idx'"
        assert "response" in predict, "Each predict must have 'response'"
        if dataset_type == "single":
            if predict.get("dataset") is not None:
                assert predict["dataset"] == name, (
                    f"Predict dataset {predict['dataset']} does not match expected {name}"
                )
            else:
                predict["dataset"] = name
        else:
            assert "dataset" in predict, "Each predict must have 'dataset'"

    dataset_list = load_memory_bench(dataset_type, name, eval_mode=True)
    if dataset_type == "single":
        dataset_list = [dataset_list]
    return _evaluate(dataset_list, predicts, on_dataset=on_dataset)


# --------------------------------------------- Summary Results ------------------------------------------------

def summary_results(
    dataset_type: Literal["single", "domain", "task"],
    name: str,
    predicts: List[Dict],
    evaluate_details: List[Dict],
    min_max_config_file: str = "configs/final_evaluate_summary_wo_details.json",
):
    def score(item):
        metrics = item.get("metrics", {})
        if BaseDataset._contains_judge_error(metrics):
            return None
        value = metrics.get("llm_judge_score")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError(f"Invalid llm_judge_score: {value!r}")
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"llm_judge_score must be in [0, 1], got {value!r}")
        return float(value)

    def statistics(total, failed):
        success = total - failed
        return {
            "total_cases": total,
            "success_cases": success,
            "failed_cases": failed,
            "success_rate": success / total if total else 0.0,
            "failure_rate": failed / total if total else 0.0,
        }

    if dataset_type == "single":
        assert len(predicts) == len(evaluate_details), (
            f"Length mismatch: {len(predicts)} vs {len(evaluate_details)}"
        )
        predict_keys = sorted((name, item["test_idx"]) for item in predicts)
        detail_keys = sorted((item.get("dataset"), item["test_idx"]) for item in evaluate_details)
        assert predict_keys == detail_keys, "Prediction/evaluation case mismatch"

        scores = []
        for item in evaluate_details:
            assert item["dataset"] == name, f"Dataset name mismatch: {item['dataset']} vs {name}"
            value = score(item)
            if value is not None:
                scores.append(value)
        return {
            "summary": {
                "llm_judge_score": sum(scores) / len(scores) if scores else None,
                "case_statistics": statistics(len(evaluate_details), len(evaluate_details) - len(scores)),
            }
        }

    config_path = min_max_config_file
    if not os.path.isabs(config_path):
        config_path = os.path.join(CURRENT_DIR, config_path)
    assert os.path.exists(config_path), f"min_max_config_file {config_path} not found"
    with open(config_path, "r") as fin:
        calibration = json.load(fin)[dataset_type][name]["summary"]
    # The current calibration file contains only LLM-judge statistics.  Keep
    # accepting files generated by the original summary script, which did not
    # include an explicit ``metric`` field.
    if calibration.get("metric", "llm_judge_score") != "llm_judge_score":
        raise ValueError("Calibration must be computed for llm_judge_score")
    dataset_min = calibration["dataset_min"]
    dataset_max = calibration["dataset_max"]
    dataset_mu = calibration["dataset_mu"]
    dataset_sigma = calibration["dataset_sigma"]

    predicts = sorted(predicts, key=lambda x: (x["dataset"], x["test_idx"]))
    evaluate_details = sorted(evaluate_details, key=lambda x: (x["dataset"], x["test_idx"]))
    assert len(evaluate_details) == len(predicts), (
        f"Length mismatch: {len(evaluate_details)} vs {len(predicts)}"
    )
    assert [(p["dataset"], p["test_idx"]) for p in predicts] == [
        (d.get("dataset"), d["test_idx"]) for d in evaluate_details
    ], "Prediction/evaluation case mismatch"

    values = {}
    case_counts = {}
    for item in tqdm(evaluate_details, desc="Merging Metrics", ascii=True, dynamic_ncols=False, ncols=80):
        dataset_name = "Locomo" if item["dataset"].startswith("Locomo") else item["dataset"]
        values.setdefault(dataset_name, [])
        case_counts.setdefault(dataset_name, {"total": 0, "failed": 0})
        case_counts[dataset_name]["total"] += 1
        value = score(item)
        if value is None:
            case_counts[dataset_name]["failed"] += 1
        else:
            values[dataset_name].append(value)

    result = {
        "summary": {},
        "average": {},
        "minmax_normalized_average": {},
        "z_normalized_average": {},
        "details": {},
        "case_statistics": {"by_dataset": {}},
    }
    for dataset_name, scores in values.items():
        result["details"][dataset_name] = scores
        counts = case_counts[dataset_name]
        result["case_statistics"]["by_dataset"][dataset_name] = statistics(
            counts["total"], counts["failed"]
        )

        result["average"][dataset_name] = sum(scores) / len(scores) if scores else None
        normalized = [
            (value - dataset_min[dataset_name])
            / (dataset_max[dataset_name] - dataset_min[dataset_name])
            if dataset_max[dataset_name] > dataset_min[dataset_name]
            else 0.0
            for value in scores
        ]
        z_scores = [
            (value - dataset_mu[dataset_name]) / dataset_sigma[dataset_name]
            if dataset_sigma[dataset_name] > 1e-6
            else 0.0
            for value in scores
        ]
        result["minmax_normalized_average"][dataset_name] = (
            sum(normalized), len(normalized), sum(normalized) / len(normalized) if normalized else None
        )
        result["z_normalized_average"][dataset_name] = (
            sum(z_scores), len(z_scores), sum(z_scores) / len(z_scores) if z_scores else None
        )

    total_cases = sum(c["total"] for c in case_counts.values())
    failed_cases = sum(c["failed"] for c in case_counts.values())
    result["case_statistics"]["overall"] = statistics(total_cases, failed_cases)

    dataset_means = [v[2] for v in result["minmax_normalized_average"].values() if v[1]]
    normalized_sums = [v[0] for v in result["minmax_normalized_average"].values() if v[1]]
    z_sums = [v[0] for v in result["z_normalized_average"].values() if v[1]]
    total_valid = sum(v[1] for v in result["minmax_normalized_average"].values())
    result["summary"] = {
        "metric": "llm_judge_score",
        "average": sum(dataset_means) / len(dataset_means) if dataset_means else None,
        "weighted_average": sum(normalized_sums) / total_valid if total_valid else None,
        "z_score": sum(z_sums) / total_valid if total_valid else None,
    }
    return result
