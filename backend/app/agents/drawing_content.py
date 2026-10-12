"""Content specialist: decide what a diagram must say before positioning shapes."""

from __future__ import annotations

import re

from app.skills.drawing_engine import DiagramError, build_diagram, parse_model_json
from app.skills.drawing_profiles import DrawingProfile, load_drawing_profile


def content_messages(prompt: str, kind: str, feedback: str = "",
                     previous_plan: dict | None = None,
                     profile: DrawingProfile | None = None) -> list[dict]:
    profile = profile or load_drawing_profile(kind)
    messages = [
        {"role": "system", "content": (
            "你是绘图内容规划 Agent。先确定读者看完图应记住的一句话，再确定阅读路径和核心节点；"
            "只规划信息结构，不计算坐标，不决定具体颜色。只输出 JSON 对象："
            '{"nodes":[{"id":"n1","label":"短名称","kind":"process|start|end|decision|database",'
            '"role":"normal|primary|support|warning|success","group":"可选分组ID"}],'
            '"edges":[{"source":"n1","target":"n2","label":"可选"}],'
            '"groups":[{"id":"g1","label":"阶段或层级"}],'
            '"visual":{"message":"一句话中心信息","focus_id":"n1",'
            '"reading_path":"left_to_right|top_to_bottom|radial"}}。'
            "节点 ID 唯一，连线只引用已有 ID；focus_id 必须是已有节点。"
            "保留用户明确提出的实体、关键判断、异常与回退，不得为了好看删掉必要信息，"
            "不要虚构流程或把并列业务串成单链。节点标签尽量控制在 18 个汉字以内，"
            "过长说明拆成子节点或分组，保留用户要求的关键术语，不要用省略号截断。"
            "仅在信息确有归属或阶段关系时使用 group，不要为了上色虚构分组。"
            "检查孤立节点和不合理串联，确保节点与连线表达用户的真实要求。"
            f"图表类型：{kind}。类型专用内容规则：{profile.content_rules}")},
        {"role": "user", "content": prompt[:12000]},
    ]
    if feedback:
        import json
        messages.append({"role": "user", "content": (
            "上一版图稿检查未通过。请根据以下问题与修改建议重新规划内容结构，"
            "保留原始用户要求，不要仅修改坐标。\n检查反馈："
            + feedback[:6000] + "\n上一版内容规划："
            + json.dumps(previous_plan or {}, ensure_ascii=False)[:9000])})
    return messages


def parse_content(raw: str, kind: str) -> dict:
    plan = parse_model_json(raw)
    if not isinstance(plan.get("nodes"), list) or not plan["nodes"]:
        raise DiagramError("内容规划没有返回节点")
    ids = [str(item.get("id") or "") for item in plan["nodes"] if isinstance(item, dict)]
    if (len(ids) != len(plan["nodes"]) or len(ids) != len(set(ids))
            or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", item) for item in ids)):
        raise DiagramError("节点必须有唯一、有效的英文 ID")
    if any(item.get("role", "normal") not in {
            "normal", "primary", "support", "warning", "success"}
            for item in plan["nodes"]):
        raise DiagramError("节点语义角色不受支持")
    groups = plan.get("groups") or []
    group_ids = [str(item.get("id") or "") for item in groups if isinstance(item, dict)]
    if (len(group_ids) != len(groups) or len(group_ids) != len(set(group_ids))
            or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,39}", item) for item in group_ids)
            or set(group_ids) & set(ids)):
        raise DiagramError("分组 ID 必须唯一，且不能与节点 ID 重复")
    if any(item.get("group") and item["group"] not in group_ids
           for item in plan["nodes"]):
        raise DiagramError("节点的分组必须引用已声明的分组 ID")
    # The renderer is also the canonical structural validator.
    build_diagram(plan, kind)
    visual = plan.get("visual") or {}
    if not isinstance(visual, dict):
        raise DiagramError("视觉简报格式不正确")
    focus_id = visual.get("focus_id")
    if focus_id is not None and focus_id not in ids:
        raise DiagramError("视觉焦点必须引用已有节点 ID")
    reading_path = visual.get("reading_path")
    if reading_path is not None and reading_path not in {
            "left_to_right", "top_to_bottom", "radial"}:
        raise DiagramError("阅读路径不受支持")
    return {"nodes": plan["nodes"], "edges": plan.get("edges", []),
            "groups": groups, "visual": visual}
