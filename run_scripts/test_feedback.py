import os
import sys
import json
import subprocess
from termcolor import colored

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import memory_systems


def _corpus_format_for(dataset_name: str, config: dict) -> str:
    try:
        from memorybench import get_dataset_class
        cls = get_dataset_class(f"src.dataset.{config[dataset_name]['class_name']}")
        return getattr(cls, "corpus_format", None)
    except Exception:
        if dataset_name.startswith("Locomo"):
            return "locomo"
        if dataset_name.startswith("DialSim"):
            return "dialsim"
        return None


with open("configs/datasets/each.json", "r") as fin:
    dataset_config = json.load(fin)


def run_script(command):
    command = command.replace("&", r"\&")
    print(colored(f"===\n\nRunning command: {command}\n\n===", "blue"))
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(colored(f"Command failed with error: \n\n{e}\n\n\n", "red"))
    print(colored(f"Finished command: {command}\n\n\n", "green"))


# Datasets without a corpus run with the default vanilla agent.
for dataset in dataset_config.keys():
    if _corpus_format_for(dataset, dataset_config) is not None:
        continue
    run_script(f"python -m src.test_feedback --dataset {dataset}")

# Locomo-family datasets get one run per registered memory baseline.
for dataset in dataset_config.keys():
    if _corpus_format_for(dataset, dataset_config) != "locomo":
        continue
    for method in memory_systems.names_with_memory():
        run_script(
            f"python -m src.test_feedback --dataset {dataset} --memory_system {method}"
        )
