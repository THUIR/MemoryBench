import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence


DEFAULT_RESULTS_REPO = "LittleDinoC/MemoryBench-Results"
EXIST_EXPS = ["off-policy"]


@dataclass(frozen=True)
class ResultEntry:
    exp: str
    model: str
    dataset_type: str
    set_name: str
    baseline: str
    run_id: str
    relative_dir: str
    files: List[str]


class MemoryBenchResults:
    """Small client for loading published MemoryBench experiment results."""

    def __init__(self, repo_id: str, entries: List[ResultEntry], repo_type: str = "dataset"):
        self.repo_id = repo_id
        self.repo_type = repo_type
        self.entries = entries
        self._index = {
            (entry.exp, entry.model, entry.dataset_type, entry.set_name, entry.baseline): entry
            for entry in entries
        }

    @classmethod
    def from_hf(
        cls,
        repo_id: str = DEFAULT_RESULTS_REPO,
        repo_type: str = "dataset",
        revision: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> "MemoryBenchResults":
        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ImportError(
                "MemoryBenchResults.from_hf requires `huggingface_hub`. "
                "Install it with `pip install huggingface_hub`."
            ) from exc

        manifest_path = hf_hub_download(
            repo_id=repo_id,
            filename="manifest.jsonl",
            repo_type=repo_type,
            revision=revision,
            cache_dir=cache_dir,
        )
        entries = _load_manifest(Path(manifest_path))
        client = cls(repo_id=repo_id, entries=entries, repo_type=repo_type)
        client.revision = revision
        client.cache_dir = cache_dir
        return client

    @classmethod
    def from_local(cls, root_dir: str, repo_id: str = "local", repo_type: str = "dataset") -> "MemoryBenchResults":
        root = Path(root_dir)
        entries = _load_manifest(root / "manifest.jsonl")
        client = cls(repo_id=repo_id, entries=entries, repo_type=repo_type)
        client.local_root = root
        return client

    def list_exps(self) -> List[str]:
        return sorted({entry.exp for entry in self.entries})

    def list_models(self, exp: Optional[str] = None) -> List[str]:
        return sorted({
            entry.model
            for entry in self.entries
            if exp is None or entry.exp == exp
        })

    def list_set_names(
        self,
        exp: Optional[str] = None,
        model: Optional[str] = None,
        dataset_type: Optional[str] = None,
    ) -> List[str]:
        return sorted({
            entry.set_name
            for entry in self.entries
            if (exp is None or entry.exp == exp)
            and (model is None or entry.model == model)
            and (dataset_type is None or entry.dataset_type == dataset_type)
        })

    def list_baselines(
        self,
        exp: Optional[str] = None,
        model: Optional[str] = None,
        dataset_type: Optional[str] = None,
        set_name: Optional[str] = None,
    ) -> List[str]:
        return sorted({
            entry.baseline
            for entry in self.entries
            if (exp is None or entry.exp == exp)
            and (model is None or entry.model == model)
            and (dataset_type is None or entry.dataset_type == dataset_type)
            and (set_name is None or entry.set_name == set_name)
        })

    def summary_table(
        self,
        metric: str,
        exp: str = "off-policy",
        dataset_type: Optional[str] = None,
        set_name: Optional[str] = None,
        baselines: Optional[Sequence[str]] = None,
        models: Optional[Sequence[str]] = None,
        missing_value=None,
        as_pandas: bool = True,
    ):
        """Build a summary metric table from summary.json's summary field."""
        models = list(models) if models is not None else self.list_models(exp=exp)
        baselines = (
            list(baselines)
            if baselines is not None
            else self.list_baselines(exp=exp, dataset_type=dataset_type, set_name=set_name)
        )
        row_entries = self._iter_entries(exp=exp, models=models, dataset_type=dataset_type, set_name=set_name)
        row_keys = sorted({
            (entry.model, entry.dataset_type, entry.set_name)
            for entry in row_entries
        })
        include_dataset_columns = set_name is None or dataset_type is None

        rows = []
        for model, row_dataset_type, row_set_name in row_keys:
            row = {"model": model}
            if include_dataset_columns:
                row["dataset_type"] = row_dataset_type
                row["set_name"] = row_set_name
            for baseline in baselines:
                try:
                    summary = self.load_summary(
                        exp=exp,
                        model=model,
                        dataset_type=row_dataset_type,
                        set_name=row_set_name,
                        baseline=baseline,
                    )
                    row[baseline] = summary.get("summary", {}).get(metric, missing_value)
                except KeyError:
                    row[baseline] = missing_value
            rows.append(row)

        if not as_pandas:
            return rows

        try:
            import pandas as pd
        except ImportError as exc:
            raise ImportError("summary_table() requires `pandas`. Install it with `pip install pandas`.") from exc
        columns = ["model"]
        if include_dataset_columns:
            columns += ["dataset_type", "set_name"]
        columns += list(baselines)
        return pd.DataFrame(rows, columns=columns)

    def _iter_entries(
        self,
        exp: Optional[str] = None,
        models: Optional[Sequence[str]] = None,
        dataset_type: Optional[str] = None,
        set_name: Optional[str] = None,
    ) -> List[ResultEntry]:
        model_set = set(models) if models is not None else None
        return [
            entry
            for entry in self.entries
            if (exp is None or entry.exp == exp)
            and (model_set is None or entry.model in model_set)
            and (dataset_type is None or entry.dataset_type == dataset_type)
            and (set_name is None or entry.set_name == set_name)
        ]

    def get_entry(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str) -> ResultEntry:
        key = (exp, model, dataset_type, set_name, baseline)
        if key not in self._index:
            raise KeyError(
                "Result not found for "
                f"exp={exp!r}, model={model!r}, dataset_type={dataset_type!r}, "
                f"set_name={set_name!r}, baseline={baseline!r}"
            )
        return self._index[key]

    def load_summary(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str) -> Dict:
        return self.load_json(exp, model, dataset_type, set_name, baseline, "summary.json")

    def load_predict(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str) -> List[Dict]:
        return self.load_json(exp, model, dataset_type, set_name, baseline, "predict.json")

    def load_evaluate_details(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str) -> List[Dict]:
        return self.load_json(exp, model, dataset_type, set_name, baseline, "evaluate_details.json")

    def load_run_config(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str) -> Dict:
        return self.load_json(exp, model, dataset_type, set_name, baseline, "run_config.json")

    def load_json(self, exp: str, model: str, dataset_type: str, set_name: str, baseline: str, filename: str):
        entry = self.get_entry(exp, model, dataset_type, set_name, baseline)
        if filename not in entry.files:
            raise FileNotFoundError(f"{filename} is not available for {entry.relative_dir}")
        path = self._resolve_file(entry, filename)
        with open(path, "r", encoding="utf-8") as fin:
            return json.load(fin)

    def _resolve_file(self, entry: ResultEntry, filename: str) -> str:
        local_root = getattr(self, "local_root", None)
        if local_root is not None:
            return str(local_root / entry.relative_dir / filename)

        try:
            from huggingface_hub import hf_hub_download
        except ImportError as exc:
            raise ImportError(
                "Loading remote result files requires `huggingface_hub`. "
                "Install it with `pip install huggingface_hub`."
            ) from exc

        return hf_hub_download(
            repo_id=self.repo_id,
            filename=f"{entry.relative_dir}/{filename}",
            repo_type=self.repo_type,
            revision=getattr(self, "revision", None),
            cache_dir=getattr(self, "cache_dir", None),
        )


def _load_manifest(path: Path) -> List[ResultEntry]:
    entries = []
    with open(path, "r", encoding="utf-8") as fin:
        for line in fin:
            if not line.strip():
                continue
            item = json.loads(line)
            exp, model = _read_exp_and_model(item)
            entries.append(
                ResultEntry(
                    exp=exp,
                    model=model,
                    dataset_type=item["dataset_type"],
                    set_name=item["set_name"],
                    baseline=item["baseline"],
                    run_id=item["run_id"],
                    relative_dir=item["relative_dir"],
                    files=list(item["files"]),
                )
            )
    return entries


def _read_exp_and_model(item: Dict) -> tuple[str, str]:
    if "exp" in item and "model" in item:
        return item["exp"], item["model"]

    setting = item["setting"]
    for exp in EXIST_EXPS:
        prefix = f"{exp}-"
        if setting.startswith(prefix):
            return exp, setting[len(prefix):]
    raise ValueError(f"Cannot parse exp/model from setting: {setting}")
