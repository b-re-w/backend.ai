from __future__ import annotations

from decimal import Decimal

from ai.backend.common.spot import drop_pooled_slots, is_spot_slot_names, is_spot_slots

SUFFIX = "-spot.shares"


def test_disabled_by_empty_suffix() -> None:
    slots = {"cpu": "2", "mem": "1024", "pro6000-spot.shares": "0.5"}
    assert not is_spot_slots(slots, "")
    assert drop_pooled_slots(slots, "") == slots


def test_spot_requires_positive_amount() -> None:
    assert is_spot_slots({"cpu": 1, "pro6000-spot.shares": Decimal("0.5")}, SUFFIX)
    assert not is_spot_slots({"cpu": 1, "pro6000-spot.shares": Decimal(0)}, SUFFIX)
    assert not is_spot_slots({"cpu": 1, "pro6000-spot.shares": "garbage"}, SUFFIX)
    assert not is_spot_slots({"cpu": 1, "pro6000.shares": 1}, SUFFIX)


def test_slot_names_only() -> None:
    assert is_spot_slot_names(["cpu", "a-spot.shares"], SUFFIX)
    assert not is_spot_slot_names(["cpu", "a.shares"], SUFFIX)
    assert not is_spot_slot_names(["a-spot.shares"], "")


def test_drop_pooled_slots_only_for_spot() -> None:
    spot = {"cpu": 2, "mem": 3, "a-spot.shares": 1, "cuda.shares": 1}
    assert drop_pooled_slots(spot, SUFFIX) == {"a-spot.shares": 1, "cuda.shares": 1}
    owner = {"cpu": 2, "mem": 3, "a.shares": 1}
    assert drop_pooled_slots(owner, SUFFIX) == owner
