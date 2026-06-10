"""Tests for the submission strategy."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.models import Container, Event, Position
from src.yard_state import YardState
from solution.offline_priority_strategy import OfflinePriorityStrategy


def _make_container(container_id: str) -> Container:
    return Container(
        container_id=container_id,
        size=20,
        weight_class="MEDIUM",
        vessel_id="VSL001",
        port_of_discharge="PORT_01",
        departure_time="2025-01-03T12:00:00",
    )


def test_strategy_avoids_blocking_earlier_retrieval():
    layout = {"blocks": {"A": {"bays": 1, "rows": 2, "tiers": 5}}}
    yard = YardState(layout)
    yard.place_container(_make_container("EARLY"), Position("A", 1, 1, 1))
    yard.place_container(_make_container("LATE"), Position("A", 1, 2, 1))

    strategy = OfflinePriorityStrategy()
    strategy.initialize(layout, {"containers": []})
    strategy._retrieval_rank = {"EARLY": 10, "NEW": 20, "LATE": 30}

    event = Event(
        event_id=1,
        timestamp="2025-01-01T00:00:00",
        type="TRUCK_RECV",
        container_id="NEW",
        weight_class="MEDIUM",
        vessel_id="VSL001",
        port_of_discharge="PORT_01",
        departure_time="2025-01-03T12:00:00",
    )

    position = strategy.place_container(yard, event)

    assert position.block == "A"
    assert position.bay == 1
    assert position.row == 2


def test_strategy_prefers_same_batch_when_blocking_is_equal():
    layout = {"blocks": {"A": {"bays": 1, "rows": 2, "tiers": 5}}}
    yard = YardState(layout)

    yard.place_container(
        Container(
            container_id="MATCH",
            size=20,
            weight_class="MEDIUM",
            vessel_id="VSL001",
            port_of_discharge="PORT_01",
            departure_time="2025-01-03T12:00:00",
        ),
        Position("A", 1, 1, 1),
    )
    yard.place_container(
        Container(
            container_id="OTHER",
            size=20,
            weight_class="LIGHT",
            vessel_id="VSL999",
            port_of_discharge="PORT_09",
            departure_time="2025-01-07T12:00:00",
        ),
        Position("A", 1, 2, 1),
    )

    strategy = OfflinePriorityStrategy()
    strategy.initialize(layout, {"containers": []})
    strategy._retrieval_rank = {"MATCH": 30, "OTHER": 40, "NEW": 20}

    event = Event(
        event_id=1,
        timestamp="2025-01-01T00:00:00",
        type="TRUCK_RECV",
        container_id="NEW",
        weight_class="MEDIUM",
        vessel_id="VSL001",
        port_of_discharge="PORT_01",
        departure_time="2025-01-03T12:00:00",
    )

    position = strategy.place_container(yard, event)

    assert position.block == "A"
    assert position.bay == 1
    assert position.row == 1


def test_strategy_falls_back_to_departure_time_when_future_order_unknown():
    layout = {"blocks": {"A": {"bays": 1, "rows": 2, "tiers": 5}}}
    yard = YardState(layout)

    yard.place_container(
        Container(
            container_id="EARLIER_DEP",
            size=20,
            weight_class="MEDIUM",
            vessel_id="VSL001",
            port_of_discharge="PORT_01",
            departure_time="2025-01-02T12:00:00",
        ),
        Position("A", 1, 1, 1),
    )
    yard.place_container(
        Container(
            container_id="LATER_DEP",
            size=20,
            weight_class="MEDIUM",
            vessel_id="VSL001",
            port_of_discharge="PORT_01",
            departure_time="2025-01-05T12:00:00",
        ),
        Position("A", 1, 2, 1),
    )

    strategy = OfflinePriorityStrategy()
    strategy.initialize(layout, {"containers": []})
    strategy._retrieval_rank = {}
    strategy._retrieval_time = {}

    event = Event(
        event_id=1,
        timestamp="2025-01-01T00:00:00",
        type="TRUCK_RECV",
        container_id="NEW",
        weight_class="MEDIUM",
        vessel_id="VSL001",
        port_of_discharge="PORT_01",
        departure_time="2025-01-03T12:00:00",
    )

    position = strategy.place_container(yard, event)

    assert position.block == "A"
    assert position.bay == 1
    assert position.row == 2
