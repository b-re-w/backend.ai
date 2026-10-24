"""Helpers for the lab's spot workloads (shared CPU/RAM pool).

A *spot* workload is a kernel (or kernel request) that asks for at least one
slot whose name ends with the configured spot-slot suffix, for example
``pro6000-spot.shares``. Spot kernels do not reserve node CPU and RAM:
those slots are served from a shared, overcommitted pool instead.

Everything is opt-in. An empty suffix (the default) disables the feature, so
no workload is ever classified as spot.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Final

#: Slots that a spot workload takes from the shared pool instead of the node.
SPOT_POOLED_SLOT_NAMES: Final[frozenset[str]] = frozenset({"cpu", "mem"})

#: Container label that marks a spot container (value ``"1"``).
SPOT_CONTAINER_LABEL: Final[str] = "ai.backend.spot"


def _is_positive(value: Any) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, ValueError):
        return False


def is_spot_slots(slots: Mapping[Any, Any], suffix: str) -> bool:
    """True if ``slots`` requests a positive amount of any ``*<suffix>`` slot.

    Always False when ``suffix`` is empty (feature disabled).
    """
    if not suffix:
        return False
    return any(str(name).endswith(suffix) and _is_positive(value) for name, value in slots.items())


def is_spot_slot_names(slot_names: Iterable[Any], suffix: str) -> bool:
    """Like :func:`is_spot_slots`, for callers that only know the slot names."""
    if not suffix:
        return False
    return any(str(name).endswith(suffix) for name in slot_names)


def drop_pooled_slots[K, V](slots: Mapping[K, V], suffix: str) -> dict[K, V]:
    """Return ``slots`` without cpu and mem when it describes a spot workload.

    Non-spot workloads (and an empty suffix) get an unchanged copy.
    """
    if not is_spot_slots(slots, suffix):
        return dict(slots)
    return {k: v for k, v in slots.items() if str(k) not in SPOT_POOLED_SLOT_NAMES}
