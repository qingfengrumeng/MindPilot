"""Validated, local design contracts for the two drawing-domain outputs."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path


PROFILE_DIR = Path(__file__).with_name("drawing_profiles")


@dataclass(frozen=True)
class DrawingProfile:
    id: str
    content_rules: str
    layout_rules: str
    review_rules: str
    connector_end_arrow: str
    layout_strategy: str
    max_retries: int
    max_layered_nodes: int
    max_layered_depth: int
    vertical_from_depth: int


@lru_cache(maxsize=2)
def load_drawing_profile(kind: str) -> DrawingProfile:
    if kind not in {"flowchart", "mindmap"}:
        raise ValueError(f"不支持的绘图类型：{kind}")
    data = json.loads((PROFILE_DIR / f"{kind}.json").read_text(encoding="utf-8"))
    if data.get("id") != kind:
        raise ValueError(f"绘图 profile 类型不匹配：{kind}")
    profile = DrawingProfile(**data)
    expected_arrow = "block" if kind == "flowchart" else "none"
    expected_layout = "adaptive_flow" if kind == "flowchart" else "radial_tree"
    if (profile.connector_end_arrow != expected_arrow
            or profile.layout_strategy != expected_layout
            or not 0 <= profile.max_retries <= 3
            or profile.max_layered_nodes < 2 or profile.max_layered_depth < 2
            or profile.vertical_from_depth < 2
            or any(not getattr(profile, key).strip() for key in
                   ("content_rules", "layout_rules", "review_rules"))):
        raise ValueError(f"绘图 profile 配置无效：{kind}")
    return profile
