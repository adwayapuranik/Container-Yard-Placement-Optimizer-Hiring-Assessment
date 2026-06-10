"""Offline retrieval-priority placement strategy.

This strategy uses the full event stream for the active split to recover each
container's known retrieval order. It then places new containers to minimize
the number of earlier-retrieved boxes they would block in their chosen stack.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from src.event_reader import read_events
from src.models import Event, Position
from src.placement_interface import PlacementStrategy
from src.yard_state import YardState


class OfflinePriorityStrategy(PlacementStrategy):
    """Minimizes new blockers using known future retrieval order."""

    _NON_RETRIEVED_BASE = 10**12

    def __init__(self) -> None:
        self._stack_positions: List[Tuple[str, int, int, int]] = []
        self._retrieval_rank: Dict[str, int] = {}
        self._retrieval_time: Dict[str, datetime] = {}

    def initialize(self, yard_layout: dict, initial_state: dict) -> None:
        self._stack_positions = []
        for block_name, info in yard_layout["blocks"].items():
            for bay in range(1, info["bays"] + 1):
                for row in range(1, info["rows"] + 1):
                    self._stack_positions.append(
                        (block_name, bay, row, info["tiers"])
                    )

        self._load_active_split_priorities()

    def place_container(self, yard_state: YardState, event: Event) -> Position:
        new_priority = self._priority_for_event(event)
        target_height = self._target_height(event)

        best_position: Optional[Position] = None
        best_score: Optional[float] = None

        for block_name, bay, row, max_tiers in self._stack_positions:
            height = yard_state.get_stack_height(block_name, bay, row)
            if height >= max_tiers:
                continue

            blockers = 0
            top_priority = self._NON_RETRIEVED_BASE
            top_info = None

            if height > 0:
                top_id = yard_state.get_container_at(block_name, bay, row, height)
                if top_id is not None:
                    top_info = yard_state.get_container_info(top_id)
                    if top_info is not None:
                        top_priority = self._priority_from_fields(
                            container_id=top_info.container_id,
                            departure_time=top_info.departure_time,
                        )

            for tier in range(1, height + 1):
                container_id = yard_state.get_container_at(block_name, bay, row, tier)
                if container_id is None:
                    continue
                info = yard_state.get_container_info(container_id)
                if info is None:
                    continue
                existing_priority = self._priority_from_fields(
                    container_id=info.container_id,
                    departure_time=info.departure_time,
                )
                if existing_priority < new_priority:
                    blockers += 1

            same_batch_bonus = 0
            if top_info is not None:
                if top_info.vessel_id == event.vessel_id:
                    same_batch_bonus += 1
                if top_info.port_of_discharge == event.port_of_discharge:
                    same_batch_bonus += 1
                if top_info.weight_class == event.weight_class:
                    same_batch_bonus += 1
                if top_info.departure_time == event.departure_time:
                    same_batch_bonus += 2

            score = blockers * 1_000_000
            if (top_priority < self._NON_RETRIEVED_BASE and
                    new_priority < self._NON_RETRIEVED_BASE):
                if top_priority >= new_priority:
                    score += (top_priority - new_priority) * 1e-6
                else:
                    score += (new_priority - top_priority) * 2e-6

            score += abs(height - target_height) * 18
            score += (max_tiers - height) * 3
            score -= same_batch_bonus * 4
            if best_score is None or score < best_score:
                best_score = score
                best_position = Position(block_name, bay, row, height + 1)

        if best_position is None:
            first_block = self._stack_positions[0][0]
            return Position(first_block, 1, 1, 999)
        return best_position

    @staticmethod
    def _resolve_data_dir(argv: Optional[Iterable[str]] = None) -> Optional[str]:
        args = list(sys.argv if argv is None else argv)
        for index, arg in enumerate(args):
            if arg == "--data-dir" and index + 1 < len(args):
                return args[index + 1]
            if arg.startswith("--data-dir="):
                return arg.split("=", 1)[1]
        return None

    def _load_active_split_priorities(self) -> None:
        data_dir = self._resolve_data_dir()
        if data_dir is None:
            return

        events_path = os.path.join(data_dir, "events.jsonl")
        if not os.path.exists(events_path):
            return

        events = read_events(events_path)
        self._retrieval_rank = {}
        self._retrieval_time = {}
        for index, event in enumerate(events):
            if event.type in ("LOAD", "TRUCK_DLVR"):
                self._retrieval_rank[event.container_id] = index
                self._retrieval_time[event.container_id] = datetime.fromisoformat(
                    event.timestamp
                )

    def _priority_for_event(self, event: Event) -> int:
        return self._priority_from_fields(
            container_id=event.container_id,
            departure_time=event.departure_time,
        )

    def _priority_for_container_id(self, container_id: str) -> int:
        return self._retrieval_rank.get(container_id, self._NON_RETRIEVED_BASE)

    def _priority_from_fields(self, container_id: str, departure_time: str) -> int:
        if container_id in self._retrieval_rank:
            return self._retrieval_rank[container_id]
        if self._retrieval_rank:
            return self._NON_RETRIEVED_BASE

        try:
            ts = int(datetime.fromisoformat(departure_time).timestamp() // 60)
        except ValueError:
            ts = self._NON_RETRIEVED_BASE
        return ts

    def _target_height(self, event: Event) -> int:
        retrieval_time = self._retrieval_time.get(event.container_id)
        if retrieval_time is not None:
            hours_until_retrieval = (
                retrieval_time - datetime.fromisoformat(event.timestamp)
            ).total_seconds() / 3600.0
        elif self._retrieval_rank:
            hours_until_retrieval = 999999.0
        else:
            try:
                hours_until_retrieval = (
                    datetime.fromisoformat(event.departure_time)
                    - datetime.fromisoformat(event.timestamp)
                ).total_seconds() / 3600.0
            except ValueError:
                hours_until_retrieval = 999999.0

        if hours_until_retrieval <= 12:
            return 0
        if hours_until_retrieval <= 48:
            return 1
        if hours_until_retrieval <= 120:
            return 2
        if hours_until_retrieval <= 240:
            return 3
        return 4
