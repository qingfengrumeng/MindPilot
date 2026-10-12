"""The conversation drawing skill: model plan -> editable draw.io XML."""

from __future__ import annotations

from dataclasses import asdict

from app.core.model_runtime import require_runtime_model
from app.services.text_generation import complete_text
from app.skills.drawing_engine import (DiagramError, apply_operations, build_diagram,
                                       catalog, connection_catalog, fast_style_edit, parse_model_json)
import json
import re


DRAWING_PROMPT = """你是专业的 draw.io 图表设计师。只返回一个 JSON 对象，不要 Markdown。
格式：{"nodes":[{"id":"n1","label":"简短中文名称","kind":"process|start|end|decision|database","group":"g1"}],"edges":[{"source":"n1","target":"n2","label":"可选"}],"groups":[{"id":"g1","label":"分层名称"}]}。
所有 id 唯一，以英文字母开头，只含英文字母、数字、下划线或短横线。连线只引用节点 id。
流程图要表达真实的步骤、分支及方向；思维导图从中心主题向外展开。必须覆盖用户明确提出的实体和关系，不要虚构细节。节点不超过 40 个、连线不超过 70 条。
当前图表类型：{kind}。"""

EDIT_PROMPT = """你是 draw.io 图表精确编辑器。仅返回 JSON，不要 Markdown。
格式：{"operations":[{"op":"set_style","target_id":"现有元素ID","style":{"fillColor":"#RRGGBB"}}]}。
还支持 rename(target_id,label)、move(target_id,x,y)、delete(target_id)、add_node(id,label,kind,x,y,parent_id)、add_edge(id,source,target,label)。
修改现有元素必须使用清单中的真实 ID。仅执行用户要求的最小改动，不要重画全图。颜色只能用 #RRGGBB。
最多返回 12 条操作。若用户要求整体完善，请依据现有节点和连接修正内容或布局，至少作出一处有意义的变化；保留与要求无关的内容和手工调整。
现有元素：{catalog}。
现有连接：{connections}。"""


DRAWING_QUALITY_GUIDE = """
排版和内容质量要求：先梳理主线、判断条件、分支结果和回退路径，再输出 JSON。
流程图通常控制在 8–18 个关键节点；只有用户明确要求完整细节时才增加节点。
不要把并列业务功能串成一条长链，也不要为无意义的过渡动作单独建节点。
不同角色、阶段或结果应形成真正的分支；判断节点的出口用简短且不同的标签（如“是”“否”）。
异常、重试和回退要连接到准确的目标节点，不能省略或虚构结果。
节点名称应短而具体，优先使用动词短语；长说明拆成相关节点或保留在用户要求的内容中。
思维导图必须有明确中心主题、一级分支和必要的二级分支；不要把所有节点平铺成中心的直接子节点。
"""


def is_edit_request(prompt: str) -> bool:
    if re.match(r"^\s*(请|帮我|给我)?\s*(画|绘制|生成|创建|制作|新建)(一[张个份])?", prompt):
        return False
    return bool(re.search(r"修改|完善|优化|改进|改成|改为|换成|变成|调整|删除|移除|重命名|加一?个?节点|新增|连接|背景.{0,12}色|颜色|move|rename|delete|change", prompt, re.I))


def generate_diagram(prompt: str, kind: str, *, model_config_path=None, complete_fn=None) -> dict:
    if kind not in {"flowchart", "mindmap"}:
        raise DiagramError("只支持流程图和思维导图")
    config = require_runtime_model("text", model_config_path)
    messages = [
        {"role": "system", "content": DRAWING_PROMPT.replace("{kind}", kind) + DRAWING_QUALITY_GUIDE},
        {"role": "user", "content": prompt[:12000]},
    ]
    for attempt in range(2):
        answer, model_meta = (complete_fn or complete_text)(config, messages)
        try:
            result = build_diagram(parse_model_json(answer), kind)
            return {**asdict(result), "model": model_meta.get("model", config.model)}
        except DiagramError as exc:
            if attempt:
                raise
            messages.extend([
                {"role": "assistant", "content": answer},
                {"role": "user", "content": f"图表规划未通过验证：{exc}。请仅返回修正后的 JSON。"},
            ])
    raise DiagramError("图表规划失败")


def edit_diagram(prompt: str, xml: str, *, model_config_path=None, complete_fn=None,
                 history: list[dict] | None = None) -> dict:
    direct = fast_style_edit(xml, prompt)
    if direct is not None:
        return {**asdict(direct), "model": "direct-edit"}
    config = require_runtime_model("text", model_config_path)
    elements = catalog(xml)
    connections = connection_catalog(xml)
    recent = [{"role": str(item.get("role") or ""), "content": str(item.get("content") or "")[:500]}
              for item in (history or [])[-8:] if isinstance(item, dict)]
    messages = [{"role": "system", "content": EDIT_PROMPT.replace("{catalog}", json.dumps(elements[:62], ensure_ascii=False))
                 .replace("{connections}", json.dumps(connections[:90], ensure_ascii=False))},
                {"role": "system", "content": "最近的编辑对话仅供理解指代；始终以当前 XML 元素清单为准："
                 + json.dumps(recent, ensure_ascii=False)},
                {"role": "user", "content": prompt[:3000]}]
    for attempt in range(2):
        answer, meta = (complete_fn or complete_text)(config, messages)
        try:
            plan = parse_model_json(answer)
            if plan.get("error"):
                raise DiagramError(str(plan["error"])[:200])
            result = apply_operations(xml, plan.get("operations"))
            return {**asdict(result), "model": meta.get("model", config.model)}
        except DiagramError as exc:
            if attempt:
                raise
            messages.extend([{"role": "assistant", "content": answer},
                             {"role": "user", "content": f"编辑操作未通过验证：{exc}。请仅返回修正后的 JSON。"}])
    raise DiagramError("图表编辑失败")
