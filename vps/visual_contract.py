"""Shared non-negotiable contract for a semantically exact visual beat."""
from __future__ import annotations


def validate_visual_contract(scene: dict, number: int | str) -> None:
    """Raise ValueError unless a scene contains checkable visual evidence.

    A semantic score alone is an assertion.  `visual_target` describes the
    action to find, while `must_show` lists the elements a reviewer must see
    inside the approved time interval.
    """
    target = scene.get("visual_target")
    must_show = scene.get("must_show")
    target_words = target.split() if isinstance(target, str) else []
    if not isinstance(target, str) or len(target.strip()) < 24 or len(target_words) < 4:
        raise ValueError(f"scene {number}: concrete visual_target is required")
    if isinstance(must_show, str):
        items = [must_show.strip()] if must_show.strip() else []
    elif isinstance(must_show, list):
        items = [str(item).strip() for item in must_show if str(item).strip()]
    else:
        items = []
    if not items:
        raise ValueError(f"scene {number}: must_show evidence is required")
