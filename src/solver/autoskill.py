from tqdm import tqdm
from typing import Dict, List

from src.agent.autoskill import AutoSkillAgent, AutoSkillAgentConfig
from src.solver.base import BaseSolver


class AutoSkillSolver(BaseSolver):
    AGENT_CLASS = AutoSkillAgent

    def __init__(self, config: AutoSkillAgentConfig, memory_cache_dir: str):
        super().__init__(config, memory_cache_dir)
        self.method_name = "AutoSkill"

    def create_or_load_memory(self, dialogs: List[Dict]):
        return super()._create_or_load_memory(dialogs, can_thread=False)

    def memory_locomo_conversation(self, conversation, session_cnt: int):
        pbar = tqdm(
            total=session_cnt,
            desc="Adding Locomo sessions to AutoSkill",
            ascii=True,
            dynamic_ncols=False,
            ncols=80,
        )
        session_idx = 1
        speaker_a = conversation.get("speaker_a", "A")
        speaker_b = conversation.get("speaker_b", "B")
        while f"session_{session_idx}" in conversation:
            session_date_time = conversation.get(f"session_{session_idx}_date_time", f"session_{session_idx}")
            session = conversation[f"session_{session_idx}"]
            messages = []
            for turn in session:
                speaker = turn.get("speaker", "")
                role = "user" if speaker == speaker_a else "assistant"
                if speaker not in {speaker_a, speaker_b}:
                    role = "user"
                text = str(turn.get("text") or "").strip()
                if text:
                    messages.append({"role": role, "content": text})
            if messages:
                self.agent.add_conversation_to_memory(
                    messages,
                    conversation_idx=f"locomo_{session_date_time}",
                )
            session_idx += 1
            pbar.update(1)

    def memory_dialsim_conversation(self, conversation, session_cnt: int):
        pbar = tqdm(
            total=session_cnt,
            desc="Adding DialSim sessions to AutoSkill",
            ascii=True,
            dynamic_ncols=False,
            ncols=80,
        )
        session_idx = 1
        while f"session_{session_idx}" in conversation:
            session_date_time = conversation.get(f"session_{session_idx}_date_time", f"session_{session_idx}")
            session = conversation[f"session_{session_idx}"]
            messages = []
            for turn in session:
                text = str(turn.get("text") or "").strip()
                if text:
                    messages.append({"role": "user", "content": text})
            if messages:
                self.agent.add_conversation_to_memory(
                    messages,
                    conversation_idx=f"dialsim_{session_date_time}",
                )
            session_idx += 1
            pbar.update(1)

    def delete_conversation_memory(self):
        raise NotImplementedError("AutoSkill does not support deleting specific conversations.")
