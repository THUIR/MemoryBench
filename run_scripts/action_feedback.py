import os
import sys
import subprocess
from termcolor import colored

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import memory_systems


def run_script(command):
    print(colored(f"===\n\nRunning command: {command}\n\n===", "blue"))
    try:
        subprocess.run(command, shell=True, check=True)
    except subprocess.CalledProcessError as e:
        print(colored(f"Command failed with error: {e}", "red"))
    print(colored(f"Finished command: {command}\n\n===", "green"))


DOMAINS = [r"Academic\&Knowledge", "Legal"]
TASKS = ["Long-Long", "Short-Short", "Short-Long", "Long-Short"]

for action in ["like", "copy"]:
    for d in DOMAINS:
        for method in memory_systems.names_with_memory():
            command = " ".join([
                "python -m src.action_feedback.predict_with_implicit_feedback",
                "--dataset_type", "domain",
                "--set_name", d,
                "--memory_system", method,
                "--action_feedback", action,
            ])
            run_script(command)
        # # SFT
        # # training
        # command = " ".join([
        #     "python -m src.action_feedback.train_sft_lora",
        #     "--dataset_type", "domain",
        #     "--set_name", d,
        #     "--action_feedback", action,
        #     "--num_epochs", "1",
        # ])
        # run_script(command)
        # # prediction
        # command = " ".join([
        #     "python -m src.action_feedback.predict_sft",
        #     "--dataset_type", "domain",
        #     "--set_name", d,
        #     "--action_feedback", action,
        #     "--num_epochs", "1",
        # ])
        # run_script(command)
