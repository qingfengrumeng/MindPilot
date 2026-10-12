"""Reviewer specialist: assess layout without changing the graph's facts."""

from __future__ import annotations

import json

from app.skills.drawing_engine import catalog, connection_catalog, parse_model, parse_model_json
from app.skills.drawing_profiles import DrawingProfile, load_drawing_profile


def review_messages(prompt: str, xml: str, kind: str, geometry_review: dict,
                    profile: DrawingProfile | None = None) -> list[dict]:
    profile = profile or load_drawing_profile(kind)
    styles = {}
    sizes = {}
    for cell in parse_model(xml).findall("./root/mxCell"):
        if cell.get("vertex") != "1":
            continue
        style = dict(part.split("=", 1) for part in cell.get("style", "").split(";")
                     if "=" in part)
        styles[cell.get("id")] = {key: style.get(key) for key in
                                  ("fillColor", "strokeColor", "fontColor", "fontSize")}
        geometry = cell.find("mxGeometry")
        if geometry is not None:
            sizes[cell.get("id")] = {"width": geometry.get("width"),
                                      "height": geometry.get("height")}
    evidence = {
        "goal": prompt[:1500], "kind": kind,
        "canvas": {"width": geometry_review["width"],
                   "height": geometry_review["height"],
                   **geometry_review.get("bounds", {})},
        "nodes": [{**node, **sizes.get(node["id"], {}),
                   "visual": styles.get(node["id"])} for node in catalog(xml)],
        "edges": connection_catalog(xml),
        "detected_layout_issues": geometry_review["findings"],
    }
    return [
        {"role": "system", "content": (
            "你是图稿检查 Agent，只审查排版，不改动图稿内容。根据画布尺寸、图形坐标、"
            "节点和连线关系判断排版是否过长、过挤、交叉复杂或分支组织不清；"
            "根据提供的 XML 样式判断焦点是否清楚、同一分支配色是否一致、文字颜色是否易读。"
            "canvas.width 是宽度而非右边界；右边界是 canvas.right。"
            "SVG 的 viewBox 已由所有图形自动计算，不要仅根据节点 x 大于 width 就断言裁切。"
            "不得声称看到了未提供的截图。仅当排版确有明显问题且可以通过重新排列节点、"
            "分组、调整焦点或配色主题修复时，返回 approved=false。"
            '只输出 JSON：{"approved":true|false,"problem":"发现的具体问题",'
            '"suggestion":"给排版 Agent 的具体修改建议"}。'
            "不得要求增删节点、修改标签或改写连线。"
            f"类型专用检查规则：{profile.review_rules}")},
        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
    ]


def parse_review(raw: str) -> tuple[bool, str, str] | None:
    try:
        answer = parse_model_json(raw)
    except (ValueError, TypeError):
        return None
    approved = answer.get("approved")
    problem = answer.get("problem", "")
    suggestion = answer.get("suggestion", "")
    if not isinstance(approved, bool):
        return None
    if approved:
        return True, "", ""
    if not isinstance(problem, str) or not isinstance(suggestion, str):
        return None
    if not problem.strip() or not suggestion.strip():
        return None
    return False, problem.strip()[:300], suggestion.strip()[:600]
