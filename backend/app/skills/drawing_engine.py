"""Compile AI graph plans to editable draw.io XML and patch existing cells safely."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import base64
import binascii
import html
import json
import re
import unicodedata
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zlib

from app.skills.drawing_profiles import DrawingProfile, load_drawing_profile


MAX_XML_BYTES = 2_000_000
MAX_NODES = 50
MAX_EDGES = 90
SAFE_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,39}$")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
COLORS = {
    "红色": "#FBE4E5", "蓝色": "#E5EDFF", "绿色": "#DDF7EA",
    "黄色": "#FFF3D5", "橙色": "#FFE8D4", "紫色": "#ECE5FF",
    "粉色": "#FCE5F2", "灰色": "#E9EEF2", "白色": "#FFFFFF",
}
STROKES = {
    "红色": "#EE6A73", "蓝色": "#6088F6", "绿色": "#46C69A",
    "黄色": "#E6B84F", "橙色": "#F3A45B", "紫色": "#9576F6",
    "粉色": "#E98AB9", "灰色": "#AABBC6", "白色": "#B9CDD9",
}

# A restrained figure-wide palette: neutral support, one focal signal and
# semantic accents. Branch colors stay consistent throughout a mind-map family.
DIAGRAM_PALETTES = {
    "ocean": {"hero": "#195D75", "text": "#263D4D", "soft": "#F1F6F8",
              "stroke": "#A9C7D0", "edge": "#66899B",
              "branches": [("#DCEEF0", "#F0F8F8", "#378997"),
                           ("#E7E6F5", "#F6F5FB", "#7774B3"),
                           ("#F7E8DB", "#FCF6F0", "#B98157"),
                           ("#E4EFDF", "#F4F9F1", "#6C9968"),
                           ("#F4E5EA", "#FBF3F6", "#AD7188")]},
    "sage": {"hero": "#356A5D", "text": "#294139", "soft": "#F2F7F3",
             "stroke": "#AECDBB", "edge": "#718D7D",
             "branches": [("#E0F0E5", "#F3FAF5", "#57976F"),
                          ("#E7EBF7", "#F5F7FC", "#7087B7"),
                          ("#F7E9E1", "#FCF5F1", "#BC8060"),
                          ("#EEE7F2", "#F8F4FA", "#9275A9"),
                          ("#F7EFE0", "#FCF9F1", "#AE9258")]},
    "indigo": {"hero": "#57598D", "text": "#303450", "soft": "#F4F4FA",
               "stroke": "#C0BFDF", "edge": "#8587AE",
               "branches": [("#E5E6F6", "#F5F5FB", "#7778B4"),
                            ("#E0F1F0", "#F2FAF9", "#559794"),
                            ("#F7E5EA", "#FCF3F6", "#B0788D"),
                            ("#F7EDDF", "#FCF8F1", "#B08E5C"),
                            ("#E7EFDF", "#F5F9F1", "#79995C")]},
    "warm": {"hero": "#915E4E", "text": "#4C3835", "soft": "#FAF5F2",
             "stroke": "#D8BCAE", "edge": "#A88678",
             "branches": [("#F7E7DE", "#FCF5F1", "#B7805F"),
                          ("#E3EFF0", "#F3F9F9", "#62949A"),
                          ("#F3E6EE", "#FBF4F8", "#A47A9A"),
                          ("#E7EDE1", "#F6F9F3", "#82946B"),
                          ("#E8EAF5", "#F6F7FB", "#7F87B2")]},
}


class DiagramError(ValueError):
    pass


@dataclass
class DiagramResult:
    xml: str
    summary: str
    nodes: int
    edges: int
    operations: list[dict]


def clean_label(value: object) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()


def _display_units(label: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
               for char in clean_label(label))


def parse_model(xml: str) -> ET.Element:
    if not isinstance(xml, str) or len(xml.encode("utf-8")) > MAX_XML_BYTES:
        raise DiagramError("图表 XML 过大或格式不正确")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise DiagramError("图表 XML 无法解析") from exc
    if root.tag == "mxGraphModel":
        return root
    if root.tag == "mxfile":
        diagram = root.find("diagram")
        if diagram is None:
            raise DiagramError("draw.io 文件没有图表页面")
        nested = diagram.find("mxGraphModel")
        if nested is not None:
            return nested
        if diagram.text:
            try:
                encoded = base64.b64decode(diagram.text.strip())
                inflater = zlib.decompressobj(-15)
                expanded = inflater.decompress(encoded, MAX_XML_BYTES + 1)
                if len(expanded) > MAX_XML_BYTES or inflater.unconsumed_tail:
                    raise DiagramError("draw.io 压缩图表过大")
                decoded = unquote(expanded.decode("utf-8"))
                model = ET.fromstring(decoded)
                if model.tag == "mxGraphModel":
                    return model
            except (ValueError, binascii.Error, zlib.error, ET.ParseError, UnicodeDecodeError) as exc:
                raise DiagramError("draw.io 压缩图表无法解析") from exc
    raise DiagramError("需要有效的 draw.io mxGraphModel 或 mxfile XML")


def serialize(model: ET.Element) -> str:
    return ET.tostring(model, encoding="unicode", short_empty_elements=True)


def empty_model() -> ET.Element:
    model = ET.Element("mxGraphModel", {
        "dx": "1400", "dy": "900", "grid": "1", "gridSize": "10",
        "guides": "1", "tooltips": "1", "connect": "1", "arrows": "1",
        "fold": "1", "page": "1", "pageScale": "1", "pageWidth": "1200",
        "pageHeight": "900", "math": "0", "shadow": "0",
    })
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    return model


def _root(model: ET.Element) -> ET.Element:
    root = model.find("root")
    if root is None:
        raise DiagramError("图表缺少 root 节点")
    return root


def catalog(xml: str) -> list[dict]:
    result = []
    for cell in _root(parse_model(xml)).findall("mxCell"):
        if cell.get("vertex") != "1":
            continue
        geometry = cell.find("mxGeometry")
        result.append({
            "id": cell.get("id", ""), "label": clean_label(cell.get("value")),
            "parent": cell.get("parent", "1"),
            "x": geometry.get("x", "0") if geometry is not None else "0",
            "y": geometry.get("y", "0") if geometry is not None else "0",
        })
    return result


def connection_catalog(xml: str) -> list[dict]:
    """Give the editor the graph topology without sending the full XML to the model."""
    return [{"id": cell.get("id", ""), "source": cell.get("source", ""),
             "target": cell.get("target", ""), "label": clean_label(cell.get("value"))}
            for cell in _root(parse_model(xml)).findall("mxCell") if cell.get("edge") == "1"]


def stats(xml: str) -> tuple[int, int]:
    cells = _root(parse_model(xml)).findall("mxCell")
    return (sum(cell.get("vertex") == "1" for cell in cells),
            sum(cell.get("edge") == "1" for cell in cells))


def _identity(raw: object, prefix: str, position: int, used: set[str]) -> str:
    proposed = str(raw or "").strip()
    if not SAFE_ID.fullmatch(proposed) or proposed in used or proposed in {"root", "layer"}:
        proposed = f"{prefix}{position}"
    while proposed in used:
        proposed += "_"
    used.add(proposed)
    return proposed


def _vertex(root: ET.Element, cell_id: str, label: str, style: str, x: int, y: int,
            width: int, height: int, parent: str = "1") -> ET.Element:
    cell = ET.SubElement(root, "mxCell", {
        "id": cell_id, "value": label[:160], "style": style,
        "vertex": "1", "parent": parent,
    })
    ET.SubElement(cell, "mxGeometry", {"x": str(x), "y": str(y), "width": str(width),
                                       "height": str(height), "as": "geometry"})
    return cell


def _edge(root: ET.Element, edge_id: str, source: str, target: str, label: str = "",
          route: dict | None = None, stroke_color: str | None = None):
    route = route or {}
    ports = "".join(f"{key}={value};" for key, value in route.get("ports", {}).items())
    feedback = route.get("kind") == "feedback"
    association = route.get("kind") == "association"
    stroke = stroke_color or ("#C68445" if feedback else "#6A8DA8")
    dash = "dashed=1;dashPattern=5 4;" if feedback else ""
    arrow = route.get("end_arrow", "none" if association else "block")
    weight = "2.4" if association else "2"
    edge = ET.SubElement(root, "mxCell", {
        "id": edge_id, "value": label[:100], "style":
        "edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;"
        f"html=1;endArrow={arrow};endFill=1;strokeColor={stroke};strokeWidth={weight};"
        f"fontColor=#43627A;fontSize=12;{dash}" + ports, "edge": "1", "parent": "1",
        "source": source, "target": target,
    })
    geometry = ET.SubElement(edge, "mxGeometry", {"relative": "1", "as": "geometry"})
    if route.get("points"):
        points = ET.SubElement(geometry, "Array", {"as": "points"})
        for x, y in route["points"]:
            ET.SubElement(points, "mxPoint", {"x": str(x), "y": str(y)})


def _flow_order(nodes: list[dict], edges: list[tuple[str, str, str]]) -> list[str]:
    """Walk from entry points, keeping branches close even when the graph has cycles."""
    ids = [node["id"] for node in nodes]
    rank = {node_id: index for index, node_id in enumerate(ids)}
    children = defaultdict(list)
    incoming = {node_id: 0 for node_id in ids}
    for source, target, _ in edges:
        if target not in children[source]:
            children[source].append(target)
        incoming[target] += 1
    starts = [node["id"] for node in nodes if node["kind"] == "start"]
    starts += [node_id for node_id in ids if incoming[node_id] == 0 and node_id not in starts]
    queue = deque(starts or ids[:1])
    order, seen = [], set()
    while queue:
        node_id = queue.popleft()
        if node_id in seen:
            continue
        seen.add(node_id)
        order.append(node_id)
        # The layout specialist's node_order controls sibling/branch order.
        # Without this, a fully connected graph ignores every retry proposal.
        queue.extend(sorted(children[node_id], key=rank.__getitem__))
    order.extend(node_id for node_id in ids if node_id not in seen)
    return order


def _flow_levels(order: list[str], edges: list[tuple[str, str, str]]) -> dict[str, int]:
    """Assign forward dependencies to columns; back edges remain explicit loops."""
    position = {node_id: index for index, node_id in enumerate(order)}
    levels = {node_id: 0 for node_id in order}
    children = defaultdict(list)
    for source, target, _ in edges:
        if position[source] < position[target]:
            children[source].append(target)
    for source in order:
        for target in children[source]:
            levels[target] = max(levels[target], levels[source] + 1)
    return levels


def _flow_branch_families(order: list[str], edges: list[tuple[str, str, str]],
                          palette: dict) -> dict[str, tuple]:
    """Keep each path from a decision in one color until paths converge."""
    position = {node_id: index for index, node_id in enumerate(order)}
    children = defaultdict(list)
    incoming = defaultdict(int)
    for source, target, _ in edges:
        if position[source] < position[target]:
            children[source].append(target)
            incoming[target] += 1
    split = next((node_id for node_id in order if len(children[node_id]) > 1), None)
    if split is None:
        return {}
    families = {}
    colors = (palette["branches"][1], palette["branches"][3],
              palette["branches"][2], palette["branches"][4])
    for branch_index, child in enumerate(children[split]):
        family = colors[branch_index % len(colors)]
        queue = deque([child])
        while queue:
            node_id = queue.popleft()
            if node_id in families or incoming[node_id] > 1:
                continue
            families[node_id] = family
            queue.extend(children[node_id])
    return families


def _flow_layout(root: ET.Element, nodes: list[dict], edges: list[tuple[str, str, str]],
                 palette: dict, focus_id: str,
                 group_colors: dict[str, tuple] | None = None,
                 profile: DrawingProfile | None = None) -> tuple[dict, str]:
    """Use a directional fork-and-join layout, with compact rows for long chains."""
    columns = 4 if len(nodes) >= 17 else 3 if len(nodes) >= 8 else 2 if len(nodes) >= 3 else 1
    by_id = {node["id"]: node for node in nodes}
    order = _flow_order(nodes, edges)
    levels = _flow_levels(order, edges)
    level_counts = [list(levels.values()).count(level) for level in set(levels.values())]
    profile = profile or load_drawing_profile("flowchart")
    layered = (len(nodes) <= profile.max_layered_nodes
               and max(levels.values()) <= profile.max_layered_depth
               and max(level_counts) <= 4 and any(count > 1 for count in level_counts))
    vertical = layered and max(levels.values()) >= profile.vertical_from_depth
    branch_families = _flow_branch_families(order, edges, palette) if layered else {}
    # When no semantic groups were supplied, contiguous reading phases provide
    # restrained wayfinding in long flows. Forked flows color each branch instead.
    phases = 3 if len(order) >= 9 else 2 if len(order) >= 4 else 1
    phase_families = (palette["branches"][0], palette["branches"][1],
                      palette["branches"][3])
    level_members = defaultdict(list)
    for node_id in order:
        level_members[levels[node_id]].append(node_id)
    widest_level = max(level_counts)
    center_y = 72 + (widest_level - 1) * 150 / 2
    center_x = 86 + (widest_level - 1) * 310 / 2
    layout = {}
    for position, node_id in enumerate(order):
        if layered:
            level = levels[node_id]
            siblings = level_members[level]
            sibling = siblings.index(node_id)
            if vertical:
                x = round(center_x + (sibling - (len(siblings) - 1) / 2) * 310)
                y = 72 + level * 158
            else:
                x = 86 + level * 310
                y = round(center_y + (sibling - (len(siblings) - 1) / 2) * 150)
        else:
            row, column = divmod(position, columns)
            if row % 2:
                column = columns - 1 - column
            x, y = 86 + column * 310, 72 + row * 150
        node = by_id[node_id]
        width, height = 248, 86
        family = (group_colors or {}).get(node.get("group", ""))
        if family is None and layered:
            family = branch_families.get(node_id, palette["branches"][0])
        elif family is None and phases > 1:
            family = phase_families[min(phases - 1, position * phases // len(order))]
        layout[node_id] = (x, y, width, height, position, levels[node_id] if layered else row)
        _vertex(root, node_id, node["label"],
                _node_style(node["kind"], "flowchart", palette,
                            focus=node_id == focus_id, role=node.get("role"),
                            branch=family),
                x, y, width, height)
    return layout, ("layered_vertical" if vertical else
                    "layered_horizontal" if layered else "compact")


def _reserve_lane(lanes: list[list[tuple[float, float]]], first: float, last: float) -> int:
    start, end = sorted((first, last))
    for index, spans in enumerate(lanes):
        if all(end + 14 < low or start - 14 > high for low, high in spans):
            spans.append((start, end))
            return index
    lanes.append([(start, end)])
    return len(lanes) - 1


def _flow_route(source: str, target: str, layout: dict, index: int,
                lanes: dict[str, list]) -> dict:
    sx, sy, sw, sh, spos, srow = layout[source]
    tx, ty, tw, th, tpos, trow = layout[target]
    scx, tcx = sx + sw / 2, tx + tw / 2
    if source == target or tpos <= spos:
        # Leave through the row gap first; a horizontal exit would cut through
        # every sibling between a right-hand source and the outside lane.
        if srow == trow:
            gap_y = sy + sh + 28 + (index % 2) * 8
            return {"kind": "feedback", "ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 1},
                    "points": [(scx, gap_y), (tcx, gap_y)]}
        source_gap, target_gap = sy - 30, ty - 30
        lane_number = _reserve_lane(lanes["left"], source_gap, target_gap)
        lane = min(x for x, _, _, _, _, _ in layout.values()) - 85 - lane_number * 24
        return {"kind": "feedback", "ports": {"exitX": .5, "exitY": 0, "entryX": .5, "entryY": 0},
                "points": [(scx, source_gap), (lane, source_gap),
                           (lane, target_gap), (tcx, target_gap)]}
    if srow == trow:
        if abs(tx - sx) <= 315:
            right = tx > sx
            return {"ports": {"exitX": 1 if right else 0, "exitY": .5,
                              "entryX": 0 if right else 1, "entryY": .5}}
        gap_y = sy + sh + 25 + (index % 2) * 10
        return {"ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 1},
                "points": [(scx, gap_y), (tcx, gap_y)]}
    if trow == srow + 1:
        gap_y = sy + sh + 38 + (index % 3) * 4
        return {"ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 0},
                "points": [] if scx == tcx else [(scx, gap_y), (tcx, gap_y)]}
    # Long cross-row connections use an external right-hand lane.
    source_gap, target_gap = sy + sh + 30, ty - 30
    lane_number = _reserve_lane(lanes["right"], source_gap, target_gap)
    lane = max(x + w for x, _, w, _, _, _ in layout.values()) + 85 + lane_number * 24
    return {"ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 0},
            "points": [(scx, source_gap), (lane, source_gap),
                       (lane, target_gap), (tcx, target_gap)]}


def _flow_route_layered(source: str, target: str, layout: dict,
                        lanes: dict[str, list], *, vertical: bool) -> dict:
    sx, sy, sw, sh, source_order, source_level = layout[source]
    tx, ty, tw, th, target_order, target_level = layout[target]
    if vertical:
        source_center, target_center = sx + sw / 2, tx + tw / 2
        if source == target:
            lane_x = sx + sw + 48
            return {"kind": "feedback",
                    "ports": {"exitX": 1, "exitY": .5, "entryX": .5, "entryY": 0},
                    "points": [(lane_x, sy + sh / 2), (lane_x, sy - 32),
                               (source_center, sy - 32)]}
        if target_order <= source_order or target_level <= source_level:
            left = min(x for x, _, _, _, _, _ in layout.values())
            lane_number = _reserve_lane(lanes["left"], ty, sy + sh)
            lane_x = left - 54 - lane_number * 26
            return {"kind": "feedback",
                    "ports": {"exitX": .5, "exitY": 1, "entryX": 0, "entryY": .5},
                    "points": [(source_center, sy + sh + 30),
                               (lane_x, sy + sh + 30),
                               (lane_x, ty + th / 2)]}
        if target_level == source_level + 1:
            gap_y = sy + sh + (ty - sy - sh) / 2
            return {"ports": {"exitX": .5, "exitY": 1,
                              "entryX": .5, "entryY": 0},
                    "points": [] if source_center == target_center else
                    [(source_center, gap_y), (target_center, gap_y)]}
        right = max(x + w for x, _, w, _, _, _ in layout.values())
        lane_number = _reserve_lane(lanes["right"], sy + sh, ty)
        lane_x = right + 54 + lane_number * 26
        return {"ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 0},
                "points": [(source_center, sy + sh + 28),
                           (lane_x, sy + sh + 28),
                           (lane_x, ty - 28), (target_center, ty - 28)]}
    if source == target:
        lane = sx + sw + 46
        return {"kind": "feedback",
                "ports": {"exitX": 1, "exitY": .5, "entryX": .5, "entryY": 0},
                "points": [(lane, sy + sh / 2), (lane, sy - 36),
                           (sx + sw / 2, sy - 36)]}
    if target_order <= source_order or target_level <= source_level:
        bottom = max(y + h for _, y, _, h, _, _ in layout.values())
        lane_number = _reserve_lane(lanes["bottom"], sx, tx)
        lane_y = bottom + 48 + lane_number * 26
        return {"kind": "feedback",
                "ports": {"exitX": .5, "exitY": 1, "entryX": .5, "entryY": 1},
                "points": [(sx + sw / 2, lane_y), (tx + tw / 2, lane_y)]}
    if target_level == source_level + 1:
        return {"ports": {"exitX": 1, "exitY": .5,
                          "entryX": 0, "entryY": .5}}
    # A skip connection travels above the process, outside the node columns.
    top = min(y for _, y, _, _, _, _ in layout.values())
    lane_number = _reserve_lane(lanes["top"], sx, tx)
    lane_y = top - 46 - lane_number * 26
    return {"ports": {"exitX": .5, "exitY": 0, "entryX": .5, "entryY": 0},
            "points": [(sx + sw / 2, lane_y), (tx + tw / 2, lane_y)]}


def _node_style(kind: str, diagram_type: str, palette: dict, *, focus: bool = False,
                branch: tuple | None = None, depth: int = 0,
                role: str | None = None) -> str:
    """Encode meaning in fill, stroke and hierarchy while retaining editable cells."""
    shape = "rounded=1;arcSize=16;"
    if diagram_type == "mindmap" and focus:
        shape = "ellipse;"
    elif kind in {"start", "end"} and diagram_type != "mindmap":
        shape = "ellipse;"
    elif kind in {"decision", "condition"} and diagram_type != "mindmap":
        shape = "rhombus;"
    elif kind in {"database", "storage"} and diagram_type != "mindmap":
        shape = "shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15;"
    fill, stroke, text = palette["soft"], palette["stroke"], palette["text"]
    if branch:
        fill = branch[0] if depth <= 1 else branch[1]
        stroke = branch[2]
    if diagram_type != "mindmap":
        if kind in {"decision", "condition"}:
            fill, stroke = "#FFF1D9", "#C48D42"
        elif kind in {"database", "storage"}:
            fill, stroke = "#E2F2EC", "#559A80"
        elif kind == "end" or role == "success":
            fill, stroke = "#E2F1E7", "#5A9A71"
        elif role == "warning":
            fill, stroke = "#F9E8E5", "#C27C72"
        elif kind == "start":
            fill, stroke = palette["branches"][0][0], palette["branches"][0][2]
        if role == "primary" and not focus:
            fill, stroke = palette["branches"][0][0], palette["branches"][0][2]
    if focus:
        fill, stroke, text = palette["hero"], palette["hero"], "#FFFFFF"
    size = 16 if focus else 15 if diagram_type == "mindmap" and depth == 1 else 14
    bold = "fontStyle=1;" if focus or role == "primary" or (diagram_type == "mindmap" and depth == 1) else ""
    base = ("whiteSpace=wrap;html=1;align=center;verticalAlign=middle;"
            f"fontFamily=Arial;fontSize={size};fontColor={text};{bold}"
            "spacing=10;strokeWidth=1.8;")
    shadow = "shadow=1;" if focus else ""
    return shape + base + shadow + f"fillColor={fill};strokeColor={stroke};"


def _mindmap_layout(root: ET.Element, nodes: list[dict],
                    edges: list[tuple[str, str, str]], palette: dict) -> tuple[dict, dict]:
    """Place descendants around their actual parent instead of flattening them."""
    node_map = {node["id"]: node for node in nodes}
    incoming = {target for _, target, _ in edges}
    center = next((node["id"] for node in nodes if node["id"] not in incoming), nodes[0]["id"])
    adjacency = defaultdict(list)
    for source, target, _ in edges:
        if target not in adjacency[source]:
            adjacency[source].append(target)
    tree = defaultdict(list)
    seen = {center}
    queue = deque([center])
    while queue:
        source = queue.popleft()
        for target in adjacency[source]:
            if target not in seen:
                seen.add(target)
                tree[source].append(target)
                queue.append(target)
    tree[center].extend(node["id"] for node in nodes if node["id"] not in seen)

    def leaves(node_id: str) -> int:
        return max(1, sum(leaves(child) for child in tree[node_id]))

    def depth(node_id: str) -> int:
        return 1 + max((depth(child) for child in tree[node_id]), default=0)

    branches = {"left": [], "right": []}
    loads = {"left": 0, "right": 0}
    for branch_index, child in enumerate(tree[center]):
        side = "right" if loads["right"] <= loads["left"] else "left"
        branches[side].append((child, branch_index))
        loads[side] += leaves(child)
    slots = max(1, *loads.values())
    max_depth = max((depth(child) for child in tree[center]), default=1)
    center_x = 145 + max_depth * 280
    center_y = 82 + slots * 108 / 2
    layout = {center: (center_x - 125, center_y - 46, 250, 92)}
    _vertex(root, center, node_map[center]["label"],
            _node_style("process", "mindmap", palette, focus=True),
            round(center_x - 125), round(center_y - 46), 250, 92)
    branch_strokes = {}

    def place(node_id: str, side: str, level: int,
              start_slot: float, branch_index: int) -> None:
        weight = leaves(node_id)
        y = 82 + (start_slot + weight / 2) * 108
        x = center_x + (1 if side == "right" else -1) * level * 280 - 115
        family = palette["branches"][branch_index % len(palette["branches"])]
        branch_strokes[node_id] = family[2]
        height = 94 if _display_units(node_map[node_id]["label"]) > 70 else 72
        layout[node_id] = (round(x), round(y - height / 2), 230, height)
        _vertex(root, node_id, node_map[node_id]["label"],
                _node_style(node_map[node_id]["kind"], "mindmap", palette,
                            branch=family, depth=level),
                round(x), round(y - height / 2), 230, height)
        cursor = start_slot
        for child in tree[node_id]:
            place(child, side, level + 1, cursor, branch_index)
            cursor += leaves(child)

    for side, items in branches.items():
        cursor = (slots - loads[side]) / 2
        for node_id, branch_index in items:
            place(node_id, side, 1, cursor, branch_index)
            cursor += leaves(node_id)
    return layout, branch_strokes


def _fit_page_to_graph(model: ET.Element) -> None:
    """Size the editable draw.io page to the artwork, including routed loops."""
    cells = _root(model).findall("mxCell")
    vertices = [cell for cell in cells if cell.get("vertex") == "1"
                and cell.get("parent") == "1"]
    points = [point for cell in cells if cell.get("edge") == "1"
              for point in cell.findall("./mxGeometry/Array[@as='points']/mxPoint")]
    bounds = []
    for cell in vertices:
        geometry = cell.find("mxGeometry")
        if geometry is None:
            continue
        x, y = float(geometry.get("x", "0")), float(geometry.get("y", "0"))
        width, height = float(geometry.get("width", "0")), float(geometry.get("height", "0"))
        bounds.extend(((x, y), (x + width, y + height)))
    bounds.extend((float(point.get("x", "0")), float(point.get("y", "0")))
                  for point in points)
    if not bounds:
        return
    left, top = min(x for x, _ in bounds), min(y for _, y in bounds)
    right, bottom = max(x for x, _ in bounds), max(y for _, y in bounds)
    shift_x, shift_y = max(0, round(44 - left)), max(0, round(44 - top))
    if shift_x or shift_y:
        for cell in vertices:
            geometry = cell.find("mxGeometry")
            if geometry is not None:
                geometry.set("x", str(round(float(geometry.get("x", "0")) + shift_x)))
                geometry.set("y", str(round(float(geometry.get("y", "0")) + shift_y)))
        for point in points:
            point.set("x", str(round(float(point.get("x", "0")) + shift_x)))
            point.set("y", str(round(float(point.get("y", "0")) + shift_y)))
    model.set("pageWidth", str(round(right + shift_x + 44)))
    model.set("pageHeight", str(round(bottom + shift_y + 44)))


def build_diagram(plan: dict, diagram_type: str) -> DiagramResult:
    if diagram_type not in {"flowchart", "architecture", "mindmap"}:
        raise DiagramError("只支持流程图、架构图和思维导图")
    profile = load_drawing_profile("mindmap" if diagram_type == "mindmap" else "flowchart")
    if not isinstance(plan, dict) or not isinstance(plan.get("nodes"), list):
        raise DiagramError("模型没有返回节点列表")
    raw_nodes = plan["nodes"]
    raw_edges = plan.get("edges", [])
    raw_groups = plan.get("groups", [])
    visual = plan.get("visual") if isinstance(plan.get("visual"), dict) else {}
    theme = visual.get("theme") or ("indigo" if diagram_type == "mindmap" else "ocean")
    palette = DIAGRAM_PALETTES.get(theme, DIAGRAM_PALETTES["ocean"])
    if not 1 <= len(raw_nodes) <= MAX_NODES or not isinstance(raw_edges, list) or len(raw_edges) > MAX_EDGES:
        raise DiagramError("图表节点或连接数量超出允许范围")
    if not isinstance(raw_groups, list) or len(raw_groups) > 12:
        raise DiagramError("图表分层数据不正确")
    model = empty_model()
    root = _root(model)
    used = {"0", "1"}
    id_map = {}
    groups = []
    for index, raw in enumerate(raw_groups, 1):
        if not isinstance(raw, dict):
            raise DiagramError("分层数据不正确")
        original = str(raw.get("id") or f"group{index}")
        gid = _identity(original, "g", index, used)
        id_map[original] = gid
        groups.append({"id": gid, "label": str(raw.get("label") or f"第 {index} 层")[:80]})
    nodes = []
    for index, raw in enumerate(raw_nodes, 1):
        if not isinstance(raw, dict) or not str(raw.get("label") or "").strip():
            raise DiagramError("存在空白节点")
        original = str(raw.get("id") or f"node{index}")
        nid = _identity(original, "n", index, used)
        id_map[original] = nid
        nodes.append({"id": nid, "label": str(raw["label"]).strip()[:160],
                      "kind": str(raw.get("kind") or "process").lower(),
                      "group": id_map.get(str(raw.get("group") or ""), ""),
                      "role": str(raw.get("role") or "normal").lower()})
    edges = []
    node_ids = {item["id"] for item in nodes}
    for index, raw in enumerate(raw_edges, 1):
        if not isinstance(raw, dict):
            raise DiagramError("连接数据不正确")
        source = id_map.get(str(raw.get("source") or ""))
        target = id_map.get(str(raw.get("target") or ""))
        if source not in node_ids or target not in node_ids:
            raise DiagramError("连接引用了不存在的节点")
        edges.append((source, target, str(raw.get("label") or "")))

    requested_focus = str(visual.get("focus_id") or "")
    focus_id = id_map.get(requested_focus)
    if focus_id not in node_ids:
        focus_id = next((node["id"] for node in nodes if node["kind"] == "start"), nodes[0]["id"])
    group_colors = {group["id"]: palette["branches"][index % len(palette["branches"])]
                    for index, group in enumerate(groups)}

    if diagram_type == "architecture" and groups:
        grouped = defaultdict(list)
        for node in nodes:
            grouped[node["group"]].append(node)
        y = 54
        for row_start in range(0, len(groups), 2):
            row_height = 0
            for column, group in enumerate(groups[row_start:row_start + 2]):
                members = grouped.pop(group["id"], [])
                rows = max(1, (len(members) + 1) // 2)
                height = 60 + rows * 116
                row_height = max(row_height, height)
                x = 60 + column * 620
                family = group_colors[group["id"]]
                group_style = (
                    "swimlane;startSize=36;horizontal=1;rounded=1;arcSize=14;html=1;"
                    f"fillColor={family[1]};swimlaneFillColor=#FFFFFF;"
                    f"strokeColor={family[2]};fontColor={palette['text']};"
                    "strokeWidth=1.5;fontStyle=1;fontFamily=Arial;fontSize=15;")
                _vertex(root, group["id"], group["label"], group_style,
                        x, y, 560, height)
                for index, node in enumerate(members):
                    _vertex(root, node["id"], node["label"],
                            _node_style(node["kind"], diagram_type, palette,
                                        focus=node["id"] == focus_id,
                                        branch=family, role=node["role"]),
                            26 + index % 2 * 265, 50 + index // 2 * 116,
                            240, 78, group["id"])
            y += row_height + 62
        ungrouped = grouped.pop("", []) + [n for rest in grouped.values() for n in rest]
        for index, node in enumerate(ungrouped):
            _vertex(root, node["id"], node["label"],
                    _node_style(node["kind"], diagram_type, palette,
                                focus=node["id"] == focus_id, role=node["role"]),
                    100 + index % 4 * 280, y + index // 4 * 116, 220, 78)
    elif diagram_type == "mindmap":
        mindmap_layout, branch_strokes = _mindmap_layout(root, nodes, edges, palette)
    else:
        flow_layout, flow_mode = _flow_layout(root, nodes, edges, palette, focus_id,
                                              group_colors, profile)
    lanes = {"left": [], "right": [], "top": [], "bottom": []}
    for index, (source, target, label) in enumerate(edges, 1):
        route = None
        if diagram_type == "flowchart":
            route = (_flow_route_layered(source, target, flow_layout, lanes,
                                         vertical=flow_mode == "layered_vertical")
                     if flow_mode.startswith("layered") else
                     _flow_route(source, target, flow_layout, index, lanes))
        if diagram_type == "mindmap":
            sx, _, sw, _ = mindmap_layout[source]
            tx, _, tw, _ = mindmap_layout[target]
            right = tx + tw / 2 >= sx + sw / 2
            route = {"kind": "association", "ports": {"exitX": 1 if right else 0, "exitY": .5,
                               "entryX": 0 if right else 1, "entryY": .5}}
        stroke = (branch_strokes.get(target, palette["edge"])
                  if diagram_type == "mindmap" else
                  "#B67D48" if route and route.get("kind") == "feedback"
                  else palette["edge"])
        route = {**(route or {}), "end_arrow": profile.connector_end_arrow}
        _edge(root, _identity(None, "e", index, used), source, target, label,
              route, stroke_color=stroke)
    _fit_page_to_graph(model)
    result = serialize(model)
    count, connections = stats(result)
    return DiagramResult(result, f"已生成可编辑图表：{count} 个元素、{connections} 条连接。",
                         count, connections, [])


def _style_map(style: str) -> dict[str, str]:
    result = {}
    for part in style.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            result[key] = value
    return result


def _write_style(cell: ET.Element, key: str, value: str):
    style = _style_map(cell.get("style", ""))
    style[key] = value
    cell.set("style", ";".join(f"{name}={item}" for name, item in style.items()) + ";")


def _resolve_target(cells: list[dict], label: str) -> dict:
    query = clean_label(label)
    exact = [cell for cell in cells if cell["id"] == query or cell["label"] == query]
    matches = exact or [cell for cell in cells if query and query in cell["label"]]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise DiagramError(f"没有找到名为「{query}」的图形元素")
    raise DiagramError(f"「{query}」匹配多个元素，请说得更具体：" + "、".join(item["label"] for item in matches[:5]))


def fast_style_edit(xml: str, instruction: str) -> DiagramResult | None:
    """Apply unambiguous colour edits directly, without replacing or re-laying out the diagram."""
    match = re.search(
        r"(?:把|将)\s*(.+?)\s*的?(?:背景色|背景|填充色|填充)\s*(?:改为|改成|换成|设为|设置为)\s*"
        r"(红色|蓝色|绿色|黄色|橙色|紫色|粉色|灰色|白色|#[0-9a-fA-F]{6})",
        instruction,
    )
    if not match:
        return None
    target = _resolve_target(catalog(xml), match.group(1))
    color_name = match.group(2)
    color = COLORS.get(color_name, color_name)
    stroke = STROKES.get(color_name)
    model = parse_model(xml)
    cell = next(cell for cell in _root(model).findall("mxCell") if cell.get("id") == target["id"])
    _write_style(cell, "fillColor", color)
    if "swimlane" in cell.get("style", ""):
        _write_style(cell, "swimlaneFillColor", color)
    if stroke:
        _write_style(cell, "strokeColor", stroke)
    updated = serialize(model)
    if updated == serialize(parse_model(xml)):
        raise DiagramError("图表没有发生变化，请给出实际可执行的修改")
    count, edges = stats(updated)
    return DiagramResult(updated, f"已将「{target['label']}」的背景改为{color_name}，其他元素保持原样。",
                         count, edges, [{"op": "set_style", "target_id": target["id"],
                                         "fillColor": color}])


def apply_operations(xml: str, operations: list[dict]) -> DiagramResult:
    if not isinstance(operations, list) or not 1 <= len(operations) <= 12:
        raise DiagramError("修改操作必须为 1 到 12 条")
    model = parse_model(xml)
    root = _root(model)
    cells = {cell.get("id"): cell for cell in root.findall("mxCell")}
    summaries = []
    allowed_style = {"fillColor", "strokeColor", "fontColor"}
    for operation in operations:
        if not isinstance(operation, dict):
            raise DiagramError("修改操作格式不正确")
        op = operation.get("op")
        target_id = str(operation.get("target_id") or "")
        if op in {"set_style", "rename", "move", "delete"}:
            target = cells.get(target_id)
            if target is None or target.get("vertex") != "1":
                raise DiagramError(f"图形元素 {target_id} 不存在")
            label = clean_label(target.get("value")) or target_id
        if op == "set_style":
            changes = operation.get("style")
            if not isinstance(changes, dict) or not changes or not set(changes).issubset(allowed_style):
                raise DiagramError("样式修改只支持填充色、边框色和文字色")
            for key, value in changes.items():
                if not HEX_COLOR.fullmatch(str(value)):
                    raise DiagramError("颜色必须是 #RRGGBB 格式")
                _write_style(target, key, str(value).upper())
                if key == "fillColor" and "swimlane" in target.get("style", ""):
                    _write_style(target, "swimlaneFillColor", str(value).upper())
            summaries.append(f"更新「{label}」的颜色")
        elif op == "rename":
            new_label = str(operation.get("label") or "").strip()
            if not new_label or len(new_label) > 160:
                raise DiagramError("新名称不能为空且不能过长")
            target.set("value", new_label)
            summaries.append(f"将「{label}」改名为「{new_label}」")
        elif op == "move":
            geometry = target.find("mxGeometry")
            if geometry is None:
                raise DiagramError("目标元素没有位置信息")
            x, y = int(operation.get("x", geometry.get("x", "0"))), int(operation.get("y", geometry.get("y", "0")))
            if not -2000 <= x <= 10000 or not -2000 <= y <= 10000:
                raise DiagramError("移动位置超出画布范围")
            geometry.set("x", str(x))
            geometry.set("y", str(y))
            summaries.append(f"移动「{label}」")
        elif op == "delete":
            removed = {target_id}
            while True:
                descendants = {cell_id for cell_id, cell in cells.items() if cell.get("parent") in removed}
                if descendants.issubset(removed):
                    break
                removed.update(descendants)
            for cell in list(root.findall("mxCell")):
                if cell.get("id") in removed or cell.get("source") in removed or cell.get("target") in removed:
                    root.remove(cell)
                    cells.pop(cell.get("id"), None)
            summaries.append(f"删除「{label}」及其连接")
        elif op == "add_node":
            label = str(operation.get("label") or "").strip()
            if not label or len(label) > 160:
                raise DiagramError("新节点名称不正确")
            new_id = _identity(operation.get("id"), "n", len(cells), set(cells))
            parent_id = str(operation.get("parent_id") or "1")
            if parent_id != "1" and (parent_id not in cells or cells[parent_id].get("vertex") != "1"):
                raise DiagramError("新增节点的分层不存在")
            siblings = sum(cell.get("parent") == parent_id and cell.get("vertex") == "1" for cell in cells.values())
            default_x = 38 + siblings % 3 * 285 if parent_id != "1" else 100 + siblings % 3 * 235
            default_y = 43 + siblings // 3 * 112 if parent_id != "1" else 100 + siblings // 3 * 145
            x = int(operation.get("x", default_x))
            y = int(operation.get("y", default_y))
            if not -2000 <= x <= 10000 or not -2000 <= y <= 10000:
                raise DiagramError("新增节点位置超出画布范围")
            cells[new_id] = _vertex(root, new_id, label,
                                    _node_style(str(operation.get("kind") or "process"),
                                                "flowchart", DIAGRAM_PALETTES["ocean"]),
                                    x, y, 200, 76, parent_id)
            summaries.append(f"新增「{label}」")
        elif op == "add_edge":
            source, target = str(operation.get("source") or ""), str(operation.get("target") or "")
            if (source not in cells or target not in cells
                    or cells[source].get("vertex") != "1" or cells[target].get("vertex") != "1"):
                raise DiagramError("新增连接引用了不存在的元素")
            new_id = _identity(operation.get("id"), "e", len(cells), set(cells))
            _edge(root, new_id, source, target, str(operation.get("label") or ""))
            cells[new_id] = root[-1]
            summaries.append("新增连接")
        else:
            raise DiagramError(f"不支持的修改操作：{op}")
    updated = serialize(model)
    if updated == serialize(parse_model(xml)):
        raise DiagramError("图表没有发生变化，请给出实际可执行的修改")
    count, edges = stats(updated)
    if count > MAX_NODES + 12 or edges > MAX_EDGES:
        raise DiagramError("修改后图表超过数量限制")
    return DiagramResult(updated, "；".join(summaries) + "。", count, edges, operations)


def parse_model_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise DiagramError("模型没有返回 JSON 图表规划") from None
        try:
            value = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise DiagramError("模型返回的 JSON 无法解析") from exc
    if not isinstance(value, dict):
        raise DiagramError("模型返回结果必须是 JSON 对象")
    return value
