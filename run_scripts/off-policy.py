import os
import sys
import subprocess
from termcolor import colored

# Allow `from src import memory_systems` when invoked from the project root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import memory_systems


def run_script(command):
    print(colored(f"===\n\nRunning command: {command}\n\n===", "blue"))
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(colored(f"Command failed with error: {e}", "red"))
    print(colored(f"Finished command: {command}\n\n===", "green"))


DOMAINS = [r"Academic\&Knowledge", "Legal", "Open-Domain"]
TASKS = ["Long-Long", "Short-Short", "Short-Long", "Long-Short"]


for method in memory_systems.all_names():
    spec = memory_systems.get(method)
    for d in DOMAINS:
        if ("domain", d) in spec.skip_combinations:
            print(colored(f"Skipping {method} on domain {d} (per registry)", "yellow"))
            continue
        command = " ".join([
            "python -m src.off-policy",
            "--dataset_type", "domain",
            "--set_name", d,
            "--memory_system", method,
        ])
        run_script(command)
    for t in TASKS:
        if ("task", t) in spec.skip_combinations:
            print(colored(f"Skipping {method} on task {t} (per registry)", "yellow"))
            continue
        command = " ".join([
            "python -m src.off-policy",
            "--dataset_type", "task",
            "--set_name", t,
            "--memory_system", method,
        ])
        run_script(command)
