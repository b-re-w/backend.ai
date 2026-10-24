"""Agent side of the spot CPU/RAM pool: alloc maps and container config."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from ai.backend.agent import resources
from ai.backend.agent.affinity_map import AffinityMap, AffinityPolicy
from ai.backend.agent.dummy.intrinsic import CPUPlugin, MemoryPlugin
from ai.backend.agent.errors import InsufficientResource
from ai.backend.agent.alloc_map import DeviceSlotInfo, DiscretePropertyAllocMap
from ai.backend.agent.resources import (
    AbstractComputeDevice,
    ComputerContext,
    build_spot_alloc_map,
)
from ai.backend.common.types import SlotTypes
from ai.backend.agent.spot import apply_spot_container_config
from ai.backend.common.spot import SPOT_CONTAINER_LABEL
from ai.backend.common.types import DeviceId, DeviceName, ResourceSlot, SlotName

SUFFIX = "-spot.shares"
GIB = 1024**3
CORES = 4
MEM = 4 * GIB
FACTOR = 4


async def _computers(suffix: str = SUFFIX) -> dict[DeviceName, ComputerContext]:
    cpu_plugin = CPUPlugin({}, {}, {"agent": {"resource": {"cpu": {"num-core": CORES}}}})
    mem_plugin = MemoryPlugin({}, {}, {"agent": {"resource": {"memory": {"size": MEM}}}})
    computers: dict[DeviceName, ComputerContext] = {}
    for name, plugin in ((DeviceName("cpu"), cpu_plugin), (DeviceName("mem"), mem_plugin)):
        base = await plugin.create_alloc_map()
        spot = build_spot_alloc_map(base, FACTOR) if suffix else None
        computers[name] = ComputerContext(plugin, await plugin.list_devices(), base, spot, suffix)
    # A stand-in accelerator whose slot name carries the spot suffix.
    gpu_dev = AbstractComputeDevice(
        DeviceId("gpu0"), "0000:01:00.0", 0, 0, device_name=DeviceName("pro6000-spot")
    )
    gpu_map = DiscretePropertyAllocMap(
        device_slots={
            DeviceId("gpu0"): DeviceSlotInfo(SlotTypes.COUNT, SlotName("pro6000-spot.shares"), Decimal(16))
        }
    )
    computers[DeviceName("pro6000-spot")] = ComputerContext(
        cpu_plugin, [gpu_dev], gpu_map, None, suffix
    )
    return computers


def _alloc(computers: dict[DeviceName, ComputerContext], slots: dict[str, str]) -> Any:
    spec = resources.KernelResourceSpec(
        ResourceSlot.from_json(slots), allocations={}, scratch_disk_size=0, mounts=[]
    )
    devices = [c for ctx in computers.values() for c in ctx.devices if ctx.instance is not None]
    resources.allocate(
        computers,
        spec,
        [DeviceName("pro6000-spot"), DeviceName("cpu"), DeviceName("mem")],
        AffinityMap.build(devices),
        AffinityPolicy.PREFER_SINGLE_NODE,
    )
    return spec


def _total(ctx_map: Any, slot: str) -> Decimal:
    return sum(ctx_map.allocations[SlotName(slot)].values(), Decimal(0))


async def test_spot_alloc_map_is_scaled_copy() -> None:
    ctxs = await _computers()
    assert ctxs[DeviceName("mem")].spot_alloc_map is not None
    mem_info = ctxs[DeviceName("mem")].spot_alloc_map.device_slots[DeviceId("root")]
    assert mem_info.amount == MEM * FACTOR
    cpu_info = ctxs[DeviceName("cpu")].spot_alloc_map.device_slots[DeviceId("0")]
    assert cpu_info.amount == FACTOR


async def test_spot_kernel_books_in_spot_map_only() -> None:
    ctxs = await _computers()
    spec = _alloc(ctxs, {"cpu": "2", "mem": str(GIB), "pro6000-spot.shares": "1"})
    assert _total(ctxs[DeviceName("cpu")].alloc_map, "cpu") == 0
    assert _total(ctxs[DeviceName("mem")].alloc_map, "mem") == 0
    assert _total(ctxs[DeviceName("cpu")].spot_alloc_map, "cpu") == 2
    assert _total(ctxs[DeviceName("mem")].spot_alloc_map, "mem") == GIB
    # allocations keep the real amounts (manager occupied_slots / stats rely on them)
    assert sum(spec.allocations[DeviceName("cpu")][SlotName("cpu")].values()) == 2
    assert sum(spec.allocations[DeviceName("mem")][SlotName("mem")].values()) == GIB


async def test_spot_can_overcommit_but_owner_cannot() -> None:
    ctxs = await _computers()
    # 3x the node memory fits in the spot map (4x), not in the real one.
    _alloc(ctxs, {"cpu": "1", "mem": str(3 * MEM), "pro6000-spot.shares": "1"})
    with pytest.raises(InsufficientResource):
        _alloc(ctxs, {"cpu": "1", "mem": str(2 * MEM), "pro6000-spot.shares": "1"})
    with pytest.raises(InsufficientResource):
        _alloc(ctxs, {"cpu": "1", "mem": str(2 * MEM)})


async def test_failed_spot_allocation_rolls_back_spot_map() -> None:
    ctxs = await _computers()
    before = _total(ctxs[DeviceName("cpu")].spot_alloc_map, "cpu")
    with pytest.raises(InsufficientResource):
        _alloc(ctxs, {"cpu": "1", "mem": str(5 * MEM), "pro6000-spot.shares": "1"})
    assert _total(ctxs[DeviceName("cpu")].spot_alloc_map, "cpu") == before


async def test_free_goes_to_the_map_that_was_booked() -> None:
    ctxs = await _computers()
    spot_spec = _alloc(ctxs, {"cpu": "2", "mem": str(GIB), "pro6000-spot.shares": "1"})
    owner_spec = _alloc(ctxs, {"cpu": "1", "mem": str(GIB)})
    for spec in (spot_spec, owner_spec):
        for dev, alloc in spec.allocations.items():
            ctxs[dev].alloc_map_for_slots(spec.slots).free(alloc)
    for ctx in ctxs.values():
        for m in filter(None, (ctx.alloc_map, ctx.spot_alloc_map)):
            assert all(v == 0 for per in m.allocations.values() for v in per.values())


async def test_owner_booking_unchanged_when_disabled() -> None:
    ctxs = await _computers(suffix="")
    _alloc(ctxs, {"cpu": "2", "mem": str(GIB), "pro6000-spot.shares": "1"})
    assert _total(ctxs[DeviceName("cpu")].alloc_map, "cpu") == 2
    assert _total(ctxs[DeviceName("mem")].alloc_map, "mem") == GIB


def _config() -> dict[str, Any]:
    return {
        "Labels": {},
        "HostConfig": {
            "Cpus": 4,
            "CpusetCpus": "0,1,2,3",
            "Memory": 8 * GIB,
            "MemorySwap": 8 * GIB,
            "Init": True,
        },
    }


def test_spot_container_config_rewrite() -> None:
    cfg = _config()
    slots = {"cpu": "4", "mem": str(8 * GIB), "pro6000-spot.shares": "0.5"}
    assert apply_spot_container_config(
        cfg, slots, spot_slot_suffix=SUFFIX, cgroup_parent="spot.slice"
    )
    host = cfg["HostConfig"]
    for key in ("Cpus", "CpusetCpus", "Memory", "MemorySwap"):
        assert key not in host
    assert host["CpuShares"] == 4 * 1024
    assert host["MemoryReservation"] == 8 * GIB
    assert host["OomScoreAdj"] == 1000
    assert host["CgroupParent"] == "spot.slice"
    assert host["Init"] is True
    assert cfg["Labels"][SPOT_CONTAINER_LABEL] == "1"


def test_spot_container_config_without_cgroup_parent() -> None:
    cfg = _config()
    slots = {"cpu": "1", "mem": str(GIB), "pro6000-spot.shares": "1"}
    assert apply_spot_container_config(cfg, slots, spot_slot_suffix=SUFFIX)
    assert "CgroupParent" not in cfg["HostConfig"]


def test_owner_container_config_untouched() -> None:
    cfg = _config()
    snapshot = {"Labels": {}, "HostConfig": dict(cfg["HostConfig"])}
    slots = {"cpu": "4", "mem": str(8 * GIB), "pro6000.shares": "0.5"}
    assert not apply_spot_container_config(
        cfg, slots, spot_slot_suffix=SUFFIX, cgroup_parent="spot.slice"
    )
    assert cfg == snapshot


def test_spot_config_disabled_by_empty_suffix() -> None:
    cfg = _config()
    snapshot = {"Labels": {}, "HostConfig": dict(cfg["HostConfig"])}
    slots = {"cpu": "4", "mem": "1", "pro6000-spot.shares": "1"}
    assert not apply_spot_container_config(cfg, slots, spot_slot_suffix="")
    assert cfg == snapshot
