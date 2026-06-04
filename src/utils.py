import os
import re
import json
import importlib
from typing import List, Tuple, Dict

from src.dataset import BaseDataset
from src import memory_systems


def get_memory_system_config_file(memory_system, memory_system_config=None):
    """Return the config-file path for `memory_system` (registry-backed)."""
    if memory_system_config is not None:
        return memory_system_config
    try:
        return memory_systems.get(memory_system).config_file
    except ValueError as e:
        raise ValueError(f"Unsupported memory system: {memory_system}") from e


def get_dialog_key(memory_system: str, prefix="dialog_") -> str:
    """Return the HF-dataset field name holding pre-generated dialogs for this method."""
    return memory_systems.get(memory_system).dialog_key(prefix)


def _resolve_corpus_format(dataset) -> str:
    """Dispatch hint for solver corpus-loading methods.

    Prefers the dataset's `corpus_format` attribute; falls back to name-prefix
    matching for any legacy BaseDataset subclass that hasn't set it yet.
    """
    fmt = getattr(dataset, "corpus_format", None)
    if fmt:
        return fmt
    name = dataset.dataset_name
    if name.startswith("Locomo-"):
        return "locomo"
    if name.startswith("DialSim-"):
        return "dialsim"
    raise ValueError(
        f"Dataset {name} has no corpus_format and is not a known corpus dataset"
    )


def load_corpus_to_memory(solver, dataset):
    """Load `dataset.corpus` into the solver's memory.

    Dispatches to `solver.memory_<corpus_format>_conversation`, where
    `corpus_format` is taken from the dataset class attribute (Locomo →
    "locomo", DialSim → "dialsim"). Solvers register a corpus by defining
    these per-format methods.
    """
    fmt = _resolve_corpus_format(dataset)
    method = getattr(solver, f"memory_{fmt}_conversation", None)
    if method is None:
        raise NotImplementedError(
            f"Solver {type(solver).__name__} does not implement "
            f"`memory_{fmt}_conversation` for corpus format '{fmt}'."
        )
    method(dataset.corpus, session_cnt=dataset.session_cnt)


def dataset_has_corpus(dataset) -> bool:
    """Whether the dataset ships a multi-session corpus."""
    return getattr(dataset, "corpus_format", None) is not None or getattr(dataset, "has_corpus", False)


def extract_json(text):
    """
    Extracts JSON content from a string, removing enclosing triple backticks and optional 'json' tag if present.
    If no code block is found, returns the text as-is.
    """
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        json_str = text  # assume it's raw JSON
    return json_str


def evaluate_and_summary(
    dataset_type: str,
    set_name: str,
    predicts: List[Dict],
    output_dir: str,
):
    from memorybench import evaluate, summary_results
    evaluate_details = evaluate(
        dataset_type, 
        set_name,
        predicts,
    )
    with open(os.path.join(output_dir, "evaluate_details.json"), "w") as fout:
        json.dump(evaluate_details, fout, indent=4, ensure_ascii=False)
    summary = summary_results(
        dataset_type,
        set_name,
        predicts,
        evaluate_details,
    )
    with open(os.path.join(output_dir, "summary.json"), "w") as fout:
        json.dump(summary, fout, indent=4, ensure_ascii=False)


# # ----------------------- [start]  loada dataset --------------------------

# def get_dataset_class(class_path):
#     module_path, class_name = class_path.rsplit('.', 1)
#     module = importlib.import_module(module_path)
#     return getattr(module, class_name)

# def get_single_dataset(dataset_name: str, config_path: str = "configs/datasets/each.json", eval_mode: bool = False) -> BaseDataset:
#     """
#     根据 dataset_name 和 config_path 获取对应的数据集实例
#     """
#     with open(config_path, "r") as fin:
#         config = json.load(fin)
#     dataset_class = BaseDataset
#     dataset_config = {}
#     for name in config:
#         if dataset_name == name:
#             dataset_class_path = config[dataset_name]["class_name"]
#             dataset_class = get_dataset_class(f"src.dataset.{dataset_class_path}")
#             dataset_config = config[dataset_name].copy()
#             # 删掉dataset_class里不需要的字段
#             for key in config[dataset_name]:
#                 if key not in dataset_class.__init__.__code__.co_varnames:
#                     del dataset_config[key]
#             dataset_config["eval_mode"] = eval_mode
#             break
#     else:
#         raise ValueError(f"Dataset {dataset_name} not found in config {config_path}")
#     dataset = dataset_class(**dataset_config)
#     return dataset

# def get_dataset_series(domain_or_task_name, config_path: str, eval_mode: bool = False) -> List[BaseDataset]:
#     with open(config_path, "r") as fin:
#         config = json.load(fin)
#     if domain_or_task_name not in config:
#         raise ValueError(f"Domain or task {domain_or_task_name} not found in config {config_path}")
#     config_list = config[domain_or_task_name]
#     dataset_list = []
#     for config in config_list:
#         dataset_class_path = config["class_name"]
#         dataset_class = get_dataset_class(f"src.dataset.{dataset_class_path}")
#         dataset_config = config.copy()
#         sample_count = dataset_config.get("sample_count", None)
#         # 删掉dataset_class里不需要的字段
#         for key in config:
#             if key not in dataset_class.__init__.__code__.co_varnames:
#                 del dataset_config[key]
#         dataset_config["eval_mode"] = eval_mode
#         dataset = dataset_class(**dataset_config)
#         dataset.sample_count = sample_count
#         dataset_list.append(dataset)
#     return dataset_list


# # ----------------------- [end]  loada dataset --------------------------

# ----------------------- [start] for memory cache -----------------------

def if_memory_cached(memory_cache_dir: str) -> bool:
    """
    Check if memory cache exists in the specified directory.

    Args:
        memory_cache_dir (str): Directory to check for memory cache.

    Returns:
        bool: True if memory cache exists, False otherwise.
    """
    memory_cache_ok_file = os.path.join(memory_cache_dir, "saved.txt")
    memory_cache_ok_content = "Memory cache saved!"
    if os.path.exists(memory_cache_ok_file):
        with open(memory_cache_ok_file, "r") as fin:
            content = fin.read()
            if content == memory_cache_ok_content:
                return True
    return False

def mark_memory_cached(memory_cache_dir: str):
    """
    Mark memory cache as saved by creating a 'saved.txt' file in the specified directory.

    Args:
        memory_cache_dir (str): Directory to mark memory cache as saved.
    """
    memory_cache_ok_file = os.path.join(memory_cache_dir, "saved.txt")
    memory_cache_ok_content = "Memory cache saved!"
    with open(memory_cache_ok_file, "w") as fout:
        fout.write(memory_cache_ok_content)

# ----------------------- [end] for memory cache -----------------------

# # ----------------------- [start] Locomo and DialSim -------------------------

# def change_dialsim_conversation_to_locomo_form(raw_text) -> Tuple[Dict, int]:
#     """
#     将 DialSim 的对话 corpus 转换为 Locomo 对话 corpus 的形式
#     Args:
#         raw_text: DialSim 格式的对话文本
    
#     Returns:
#         conversation: 转换后的对话 dict
#         session_cnt: 对话的轮数
#     """
#     conversation = {}
#     session_pattern = re.compile(r"\[Date: (.*?), Session #(\d+)\]\n\n(.*?)(?=(?:\[Date:)|$)", re.S)
#     sessions = session_pattern.findall(raw_text)

#     for sid, session in enumerate(sessions, start=1):
#         date_str, session_num, session_text = session
#         session_date_time = f"{date_str}, Session #{session_num}"
#         conversation[f"session_{sid}_date_time"] = session_date_time
#         sess = [] 
#         lines = session_text.strip().split("\n")
#         for idx, line in enumerate(lines, start=1):
#             # 匹配 "Speaker: text"
#             match = re.match(r"^(.*?):\s*(.*)$", line)
#             if match:
#                 speaker, text = match.groups()
#                 sess.append({
#                     "speaker": speaker.strip(),
#                     "dia_id": f"D{session_num}:{idx}",
#                     "text": text.strip()
#                 })
#         conversation[f"session_{sid}"] = sess
#     return conversation, len(sessions)

# # ----------------------- [end] Locomo and DialSim ------------------------- 