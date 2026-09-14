from tqdm import tqdm
from typing import List, Dict
from datetime import datetime, timezone

from dateutil import parser as date_parser

from src.agent.graphiti import GraphitiAgent, GraphitiAgentConfig
from src.solver.base import BaseSolver


def _parse_session_time(session_date_time: str) -> datetime:
    try:
        dt = date_parser.parse(session_date_time)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, OverflowError):
        return datetime.now(timezone.utc)


class GraphitiSolver(BaseSolver):
    AGENT_CLASS = GraphitiAgent

    def __init__(self, config: GraphitiAgentConfig, memory_cache_dir: str):
        super().__init__(config, memory_cache_dir)
        self.method_name = "Graphiti"
        self.current_conversation_episodes = []

    def create_or_load_memory(self, dialogs: List[Dict]):
        # Graph episodes must be ingested sequentially: Graphiti links each
        # episode to the previous ones and Kuzu allows a single writer.
        super()._create_or_load_memory(dialogs, can_thread=False)

    def _memory_sessions(self, conversation, session_cnt: int):
        pbar = tqdm(total=session_cnt, desc="Adding new conversation to memory", ascii=True, dynamic_ncols=False, ncols=80)
        chunk_size = self.agent.config.messages_per_episode
        session_idx = 1
        while f"session_{session_idx}" in conversation:
            session_date_time = conversation[f"session_{session_idx}_date_time"]
            session = conversation[f"session_{session_idx}"]
            reference_time = _parse_session_time(session_date_time)
            turns = [f"{turn['speaker']} says: {turn['text']}" for turn in session]
            for chunk_idx in range(0, len(turns), chunk_size):
                episode_body = "\n".join(turns[chunk_idx:chunk_idx + chunk_size])
                for attempt in range(5):
                    try:
                        episode_uuid = self.agent.add_episode(
                            name=f"session-{session_idx}-part-{chunk_idx // chunk_size}",
                            episode_body=episode_body,
                            source_description=f"conversation session at {session_date_time}",
                            reference_time=reference_time,
                        )
                        self.current_conversation_episodes.append(episode_uuid)
                        break
                    except Exception as e:
                        print(f"[Graphiti] Error adding session episode (attempt {attempt + 1}): {e}")
            session_idx += 1
            pbar.update(1)

    def memory_locomo_conversation(self, conversation, session_cnt: int):
        self._memory_sessions(conversation, session_cnt)

    def memory_dialsim_conversation(self, conversation, session_cnt: int):
        self._memory_sessions(conversation, session_cnt)

    def delete_conversation_memory(self):
        for episode_uuid in self.current_conversation_episodes:
            try:
                self.agent.remove_episode(episode_uuid)
            except Exception:
                print(f"Episode {episode_uuid} not found for deletion.")
        self.current_conversation_episodes = []
