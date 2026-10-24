"""Container config rewrite for spot kernels (shared CPU/RAM pool).

Owner containers keep the hard limits the intrinsic cpu/mem plugins give them
(``Cpus``, ``CpusetCpus``, ``Memory``, ``MemorySwap``). A spot container instead
shares the pool: soft limits only, the highest OOM score so the kernel kills it
before anything else, and optionally a parent cgroup (a systemd slice) that caps
the whole pool. See ``ai.backend.common.spot``.
"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from decimal import Decimal
from typing import Any

from ai.backend.common.spot import SPOT_CONTAINER_LABEL, is_spot_slots

_HARD_LIMIT_KEYS = (
    "Cpus",
    "NanoCpus",
    "CpusetCpus",
    "CpuQuota",
    "CpuPeriod",
    "Memory",
    "MemorySwap",
)
_CPU_SHARES_PER_CORE = 1024
_MAX_OOM_SCORE_ADJ = 1000


def apply_spot_container_config(
    container_config: MutableMapping[str, Any],
    slots: Mapping[Any, Any],
    *,
    spot_slot_suffix: str,
    cgroup_parent: str = "",
) -> bool:
    """Rewrite ``container_config`` in place for a spot kernel.

    Returns False and leaves the config untouched when the kernel is not a spot
    kernel (including when ``spot_slot_suffix`` is empty).
    """
    if not is_spot_slots(slots, spot_slot_suffix):
        return False
    requested = {str(name): value for name, value in slots.items()}
    cores = Decimal(str(requested.get("cpu", 0)))
    mem = int(Decimal(str(requested.get("mem", 0))))

    host_config: MutableMapping[str, Any] = container_config.setdefault("HostConfig", {})
    for key in _HARD_LIMIT_KEYS:
        host_config.pop(key, None)
    host_config["CpuShares"] = max(2, int(cores * _CPU_SHARES_PER_CORE))
    if mem > 0:
        host_config["MemoryReservation"] = mem
    host_config["OomScoreAdj"] = _MAX_OOM_SCORE_ADJ
    if cgroup_parent:
        host_config["CgroupParent"] = cgroup_parent
    container_config.setdefault("Labels", {})[SPOT_CONTAINER_LABEL] = "1"
    return True
