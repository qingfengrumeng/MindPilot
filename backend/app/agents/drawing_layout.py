"""Layout specialist: choose grouping and node order without changing graph facts."""

from __future__ import annotations

import json

from app.skills.drawing_engine import DiagramError, parse_model_json
from app.skills.drawing_profiles import DrawingProfile, load_drawing_profile


def layout_messages(plan: dict, kind: str, feedback: str = "",
                    profile: DrawingProfile | None = None) -> list[dict]:
    profile = profile or load_drawing_profile(kind)
    messages = [
        {"role": "system", "content": (
            "你是绘图排版设计 Agent。按照视觉简报决定清晰的阅读路径、焦点和留白；"
            "不得增加、删除或改写节点及连线。只输出 JSON："
            '{"layout_mode":"flow|layers|mindmap","node_order":["节点ID"],'
            '"group_order":["分组ID"],"theme":"ocean|sage|indigo|warm",'
            '"focus_id":"已有节点ID"}。'
            "只使用一套低饱和配色；根据主题选 ocean/sage/indigo/warm，"
            "颜色按业务阶段与分支家族连续分配，结果/成功/警示由语义色承载，"
            "不要每个节点随机换色，也不要仅靠颜色表达关系。"
            "图中只强调一个核心节点，其他元素退居辅助层级。"
            "根据节点数量和标签长度安排画布，保持节点间距、边距及连线通道；"
            "避免重叠、文字截断和大片无意义的空白。"
            "node_order 应覆盖所有节点且不重复。"
            f"类型专用排版规则：{profile.layout_rules}")},
        {"role": "user", "content": json.dumps({"kind": kind, "plan": plan}, ensure_ascii=False)},
    ]
    if feedback:
        messages.append({"role": "user", "content": (
            "上一版图稿检查未通过。以下 JSON 包含每次检查发现的问题、修改建议及上次排版方案。"
            "请逐条落实修改建议，避免重复失败的排版，重新安排节点和分组顺序；"
            "不得更改节点、连线或标签；必要时在 flow 与 layers 间切换："
            + feedback[:5000])})
    return messages


def apply_layout(raw: str, plan: dict, kind: str) -> tuple[dict, str]:
    design = parse_model_json(raw)
    mode = design.get("layout_mode", "mindmap" if kind == "mindmap" else "flow")
    if kind == "mindmap":
        mode = "mindmap"
    elif mode not in {"flow", "layers"}:
        raise DiagramError("排版方式不受支持")
    node_ids = [str(item.get("id")) for item in plan["nodes"]]
    order = design.get("node_order")
    if order is not None:
        if (not isinstance(order, list) or not all(isinstance(item, str) for item in order)
                or len(order) != len(node_ids) or set(order) != set(node_ids)):
            raise DiagramError("排版顺序必须恰好包含所有节点 ID")
        ranks = {node_id: index for index, node_id in enumerate(order)}
        plan = {**plan, "nodes": sorted(plan["nodes"], key=lambda node: ranks[str(node["id"])])}
    groups = plan.get("groups") or []
    group_order = design.get("group_order")
    if group_order is not None and groups:
        group_ids = [str(item.get("id")) for item in groups]
        if (not isinstance(group_order, list) or not all(isinstance(item, str) for item in group_order)
                or len(group_order) != len(group_ids) or set(group_order) != set(group_ids)):
            raise DiagramError("分组顺序必须恰好包含所有分组 ID")
        ranks = {group_id: index for index, group_id in enumerate(group_order)}
        plan = {**plan, "groups": sorted(groups, key=lambda group: ranks[str(group["id"])])}
    if mode == "layers" and not groups:
        mode = "flow"
    theme = design.get("theme", "indigo" if kind == "mindmap" else "ocean")
    if theme not in {"ocean", "sage", "indigo", "warm"}:
        raise DiagramError("配色方案不受支持")
    visual = dict(plan.get("visual") or {})
    focus_id = design.get("focus_id", visual.get("focus_id"))
    if focus_id is not None and focus_id not in node_ids:
        raise DiagramError("视觉焦点必须引用已有节点 ID")
    visual.update({"theme": theme, "focus_id": focus_id})
    plan = {**plan, "visual": visual}
    return plan, mode
