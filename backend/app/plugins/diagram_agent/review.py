"""Inspect the actual editable graph and SVG before the drawing domain publishes them."""

from __future__ import annotations

from collections import Counter
import xml.etree.ElementTree as ET

from app.skills.drawing_engine import DiagramError, clean_label, parse_model
from app.skills.drawing_preview import _edge_points, _number, _style, _wrapped_lines


def _boxes(cells: dict[str, ET.Element]) -> dict[str, tuple[float, float, float, float]]:
    boxes = {}

    def locate(cell_id: str, visiting: set[str]) -> tuple[float, float, float, float]:
        if cell_id in boxes:
            return boxes[cell_id]
        if cell_id in visiting:
            raise DiagramError("图稿存在循环嵌套的分组")
        cell = cells[cell_id]
        geometry = cell.find("mxGeometry")
        if geometry is None:
            raise DiagramError(f"图形 {cell_id} 缺少坐标")
        try:
            x = float(geometry.get("x", "0"))
            y = float(geometry.get("y", "0"))
            width = float(geometry.get("width", "0"))
            height = float(geometry.get("height", "0"))
        except ValueError as exc:
            raise DiagramError(f"图形 {cell_id} 坐标无效") from exc
        if width <= 0 or height <= 0:
            raise DiagramError(f"图形 {cell_id} 大小无效")
        parent_id = cell.get("parent")
        if parent_id in cells and cells[parent_id].get("vertex") == "1":
            parent_x, parent_y, _, _ = locate(parent_id, visiting | {cell_id})
            x += parent_x
            y += parent_y
        boxes[cell_id] = (x, y, width, height)
        return boxes[cell_id]

    for cell_id, cell in cells.items():
        if cell.get("vertex") == "1":
            locate(cell_id, set())
    return boxes


def inspect_diagram(xml: str, svg: str, *, plan: dict | None = None,
                    editing: bool = False, kind: str | None = None) -> dict:
    """Return blocking integrity errors and actionable layout feedback separately."""
    model = parse_model(xml)
    root = model.find("root")
    if root is None:
        raise DiagramError("图表缺少 root 节点")
    cells = {cell.get("id"): cell for cell in root.findall("mxCell") if cell.get("id")}
    boxes = _boxes(cells)
    edges = [cell for cell in cells.values() if cell.get("edge") == "1"]
    hard = []
    soft = []
    findings = []

    def report(problem: str, suggestion: str) -> None:
        findings.append({"problem": problem, "suggestion": suggestion})
        soft.append(f"{problem}；修改建议：{suggestion}")

    for edge in edges:
        if edge.get("source") not in boxes or edge.get("target") not in boxes:
            hard.append(f"连线 {edge.get('id')} 指向不存在的图形")
        if kind in {"flowchart", "mindmap"} and not editing:
            arrow = _style(edge).get("endArrow", "block")
            expected = "block" if kind == "flowchart" else "none"
            if arrow != expected:
                hard.append(f"{kind} 连线 {edge.get('id')} 的方向样式不正确")
    if plan is not None:
        expected_nodes = {str(node["id"]) for node in plan["nodes"]}
        if expected_nodes - boxes.keys():
            hard.append("图稿缺少已规划节点")
        expected_edges = Counter((str(edge["source"]), str(edge["target"]))
                                 for edge in plan.get("edges", []))
        actual_edges = Counter((edge.get("source"), edge.get("target")) for edge in edges)
        if expected_edges != actual_edges:
            hard.append("图稿连线与内容规划不一致")
    svg_root = ET.fromstring(svg)
    try:
        canvas_x, canvas_y, canvas_width, canvas_height = (
            float(value) for value in svg_root.attrib["viewBox"].split())
    except (KeyError, ValueError) as exc:
        raise DiagramError("图稿预览缺少有效画布范围") from exc
    if canvas_width <= 0 or canvas_height <= 0:
        hard.append("图稿预览画布为空")
    if (canvas_width > 0 and canvas_height > 0 and not editing and len(boxes) >= 5
            and max(canvas_width / canvas_height, canvas_height / canvas_width) > 3.4):
        report(f"画布宽高比例过大（约 {max(canvas_width / canvas_height, canvas_height / canvas_width):.1f}:1），图稿呈长条状",
               "缩短主线，将并列分支横向分布，并调整节点或分组顺序")

    # Group containers intentionally enclose their children. Compare only leaf shapes.
    container_ids = {cell.get("parent") for cell in cells.values()
                     if cell.get("parent") in boxes}
    leaf_boxes = [(cell_id, box) for cell_id, box in boxes.items()
                  if cell_id not in container_ids]
    clipped = []
    for cell_id, (_, _, width, height) in leaf_boxes:
        cell = cells[cell_id]
        label = clean_label(cell.get("value", ""))
        style = _style(cell)
        is_diamond = "rhombus" in cell.get("style", "")
        font_size = max(11, min(20, _number(style.get("fontSize"), 13)))
        lines = _wrapped_lines(label, width * (.72 if is_diamond else 1),
                               2 if height < 70 else 4 if height >= 92 else 3,
                               font_size)
        if lines and lines[-1].endswith("…"):
            clipped.append(cell_id)
    if clipped and not editing:
        report(f"有 {len(clipped)} 个节点标签在预览中被截断",
               "缩短这些节点的标签，必要时拆成独立子节点：" + "、".join(clipped[:6]))
    overlaps = 0
    for index, (_, first) in enumerate(leaf_boxes):
        x1, y1, w1, h1 = first
        for _, second in leaf_boxes[index + 1:]:
            x2, y2, w2, h2 = second
            overlap_width = min(x1 + w1, x2 + w2) - max(x1, x2)
            overlap_height = min(y1 + h1, y2 + h2) - max(y1, y2)
            if overlap_width > 8 and overlap_height > 8:
                overlaps += 1
    if overlaps:
        report(f"有 {overlaps} 对图形相互遮挡",
               "拉开冲突节点，重新安排相邻节点和分组的顺序")
    crossings = 0
    for edge in edges:
        source, target = edge.get("source"), edge.get("target")
        if source not in boxes or target not in boxes:
            continue
        path = _edge_points(edge, boxes[source], boxes[target])
        for cell_id, (x, y, node_width, node_height) in leaf_boxes:
            if cell_id in {source, target}:
                continue
            for (x1, y1), (x2, y2) in zip(path, path[1:]):
                if abs(y1 - y2) < 1 and y + 5 < y1 < y + node_height - 5:
                    if min(x + node_width - 5, max(x1, x2)) - max(x + 5, min(x1, x2)) > 12:
                        crossings += 1
                        break
                elif abs(x1 - x2) < 1 and x + 5 < x1 < x + node_width - 5:
                    if min(y + node_height - 5, max(y1, y2)) - max(y + 5, min(y1, y2)) > 12:
                        crossings += 1
                        break
    if crossings:
        report(f"有 {crossings} 处连线穿过其他图形",
               "把相关分支放到相邻区域，并调整节点顺序以给连线留出通道")
    return {"approved": not hard and not soft, "hard_issues": hard,
            "layout_issues": soft, "findings": findings,
            "width": round(canvas_width), "height": round(canvas_height),
            "bounds": {"left": round(canvas_x), "top": round(canvas_y),
                       "right": round(canvas_x + canvas_width),
                       "bottom": round(canvas_y + canvas_height)},
            "nodes": len(boxes), "edges": len(edges)}
