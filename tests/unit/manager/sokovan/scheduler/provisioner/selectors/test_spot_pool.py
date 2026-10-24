"""Spot kernels do not fit-check or book cpu and mem on the agent."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from ai.backend.common.identifier.architecture import ArchName
from ai.backend.common.identifier.resource_slot import ResourceSlotName
from ai.backend.common.types import AgentId, ClusterMode
from ai.backend.manager.sokovan.scheduler.provisioner.selectors.filters.stateful.resource import (
    ResourceTrackerFilter,
)
from ai.backend.manager.sokovan.scheduler.provisioner.selectors.selector import PlacementPlan
from ai.backend.manager.sokovan.scheduler.provisioner.selectors.tracker import AgentStateTracker
from ai.backend.manager.sokovan.scheduler.provisioner.selectors.types import ResourceRequirements
from ai.backend.manager.views.sokovan.agent import AgentInfo, AgentResource, SlotResource
from ai.backend.manager.views.sokovan.workload import ResourceRequest

SUFFIX = "-spot.shares"
CPU = ResourceSlotName("cpu")
MEM = ResourceSlotName("mem")
SPOT = ResourceSlotName("pro6000-spot.shares")


def _req(slots: Mapping[ResourceSlotName, str]) -> ResourceRequirements:
    return ResourceRequirements(
        requested_slots=ResourceRequest(slots={k: Decimal(v) for k, v in slots.items()}),
        required_architecture=ArchName("x86_64"),
        container_count=1,
    )


def _tracker(cpu_free: str, mem_free: str) -> AgentStateTracker:
    return AgentStateTracker(
        original_agent=AgentInfo(
            agent_id=AgentId("a1"),
            agent_addr="a1:6001",
            architecture=ArchName("x86_64"),
            resources=AgentResource(
                slots={
                    CPU: SlotResource(Decimal(cpu_free), Decimal(0), Decimal(0)),
                    MEM: SlotResource(Decimal(mem_free), Decimal(0), Decimal(0)),
                    SPOT: SlotResource(Decimal(16), Decimal(0), Decimal(0)),
                }
            ),
            container_count=0,
        )
    )


class TestPlacementPlanSpot:
    def test_spot_item_drops_cpu_and_mem(self) -> None:
        plan = PlacementPlan.from_items(
            [_req({CPU: "64", MEM: "999999", SPOT: "1"})], ClusterMode.SINGLE_NODE, SUFFIX
        )
        assert plan.requirements()[0].requested_slots.slots == {SPOT: Decimal(1)}

    def test_disabled_keeps_everything(self) -> None:
        plan = PlacementPlan.from_items(
            [_req({CPU: "64", MEM: "100", SPOT: "1"})], ClusterMode.SINGLE_NODE
        )
        assert set(plan.requirements()[0].requested_slots.slots) == {CPU, MEM, SPOT}

    def test_owner_item_is_untouched(self) -> None:
        owner = _req({CPU: "4", MEM: "100"})
        plan = PlacementPlan.from_items([owner], ClusterMode.SINGLE_NODE, SUFFIX)
        assert plan.requirements()[0].requested_slots.slots == owner.requested_slots.slots

    def test_mixed_single_node_sums_only_owner_cpu_mem(self) -> None:
        plan = PlacementPlan.from_items(
            [_req({CPU: "4", MEM: "100"}), _req({CPU: "64", MEM: "900", SPOT: "1"})],
            ClusterMode.SINGLE_NODE,
            SUFFIX,
        )
        slots = plan.requirements()[0].requested_slots.slots
        assert slots[CPU] == Decimal(4)
        assert slots[MEM] == Decimal(100)
        assert slots[SPOT] == Decimal(1)

    def test_multi_node_decided_per_item(self) -> None:
        plan = PlacementPlan.from_items(
            [_req({CPU: "4", MEM: "100"}), _req({CPU: "64", SPOT: "1"})],
            ClusterMode.MULTI_NODE,
            SUFFIX,
        )
        first, second = plan.requirements()
        assert CPU in first.requested_slots.slots
        assert CPU not in second.requested_slots.slots


class TestFilterAndTrackerIgnoreSpotCpuMem:
    def test_spot_fits_an_agent_without_free_cpu_mem(self) -> None:
        tracker = _tracker(cpu_free="0", mem_free="0")
        flt = ResourceTrackerFilter()
        raw = _req({CPU: "64", MEM: "999999", SPOT: "1"})
        stripped = raw.without_spot_pooled_slots(SUFFIX)
        assert flt._has_room(tracker, raw) is False
        assert flt._has_room(tracker, stripped) is True

    def test_owner_still_needs_room(self) -> None:
        tracker = _tracker(cpu_free="2", mem_free="100")
        flt = ResourceTrackerFilter()
        too_big = _req({CPU: "4", MEM: "10"}).without_spot_pooled_slots(SUFFIX)
        fits = _req({CPU: "2", MEM: "10"}).without_spot_pooled_slots(SUFFIX)
        assert flt._has_room(tracker, too_big) is False
        assert flt._has_room(tracker, fits) is True

    def test_tracker_does_not_book_spot_cpu_mem(self) -> None:
        tracker = _tracker(cpu_free="8", mem_free="100")
        stripped = _req({CPU: "64", MEM: "900", SPOT: "1"}).without_spot_pooled_slots(SUFFIX)
        tracker.apply_diff(stripped.requested_slots, 1, None)
        tracker.commit()
        remaining = tracker.remaining_slots()
        assert remaining[CPU] == Decimal(8)
        assert remaining[MEM] == Decimal(100)
        assert remaining[SPOT] == Decimal(15)
