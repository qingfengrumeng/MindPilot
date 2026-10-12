"""Small static SVG preview for native draw.io cells in chat messages."""

from __future__ import annotations

import html
import re
import unicodedata

from app.skills.drawing_engine import DiagramError, clean_label, parse_model


def _number(value: str | None, default: float = 0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _style(cell) -> dict[str, str]:
    return dict(part.split("=", 1) for part in cell.get("style", "").split(";") if "=" in part)


def _color(value: str | None, fallback: str) -> str:
    return value if value and re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback


def _edge_points(cell, source, target):
    sx, sy, sw, sh = source
    tx, ty, tw, th = target
    style = _style(cell)
    geometry = cell.find("mxGeometry")
    bends = []
    if geometry is not None:
        points = geometry.find("Array[@as='points']")
        if points is not None:
            bends = [(_number(point.get("x")), _number(point.get("y")))
                     for point in points.findall("mxPoint")]
    if "exitX" in style and "entryX" in style:
        start = (sx + sw * _number(style.get("exitX"), .5),
                 sy + sh * _number(style.get("exitY"), .5))
        end = (tx + tw * _number(style.get("entryX"), .5),
               ty + th * _number(style.get("entryY"), .5))
    else:
        dx = tx + tw / 2 - sx - sw / 2
        dy = ty + th / 2 - sy - sh / 2
        if abs(dx) > abs(dy):
            start = (sx + (sw if dx >= 0 else 0), sy + sh / 2)
            end = (tx + (0 if dx >= 0 else tw), ty + th / 2)
        else:
            start = (sx + sw / 2, sy + (sh if dy >= 0 else 0))
            end = (tx + tw / 2, ty + (0 if dy >= 0 else th))
    if not bends and start[0] != end[0] and start[1] != end[1]:
        # The left/right ports used by mind maps need a vertical branching
        # spine between columns. Routing through the middle Y instead sends
        # each edge along a node's column and makes branches look tangled.
        horizontal_ports = (style.get("exitX") in {"0", "1"}
                            and style.get("entryX") in {"0", "1"})
        if horizontal_ports or abs(end[0] - start[0]) > abs(end[1] - start[1]):
            middle = (start[0] + end[0]) / 2
            bends = [(middle, start[1]), (middle, end[1])]
        else:
            middle = (start[1] + end[1]) / 2
            bends = [(start[0], middle), (end[0], middle)]
    return [start, *bends, end]


def _edge_label_anchor(points):
    segments = list(zip(points, points[1:]))
    horizontal = [(abs(end[0] - start[0]), start, end) for start, end in segments
                  if abs(end[1] - start[1]) < 1]
    if horizontal:
        _, start, end = max(reversed(horizontal), key=lambda item: item[0])
        return (start[0] + end[0]) / 2, start[1] - 8
    start, end = max(segments, key=lambda pair: abs(pair[1][1] - pair[0][1]))
    return start[0] + 8, (start[1] + end[1]) / 2 - 8


def _rounded_path(points: list[tuple[float, float]], radius: float = 9) -> str:
    """Match draw.io's rounded orthogonal connectors in the SVG preview."""
    if not points:
        return ""
    compact = [points[0]]
    for point in points[1:]:
        if point != compact[-1]:
            compact.append(point)
    path = f"M{compact[0][0]:g} {compact[0][1]:g}"
    for index in range(1, len(compact) - 1):
        before, corner, after = compact[index - 1:index + 2]
        inbound = (corner[0] - before[0], corner[1] - before[1])
        outbound = (after[0] - corner[0], after[1] - corner[1])
        in_length = abs(inbound[0]) + abs(inbound[1])
        out_length = abs(outbound[0]) + abs(outbound[1])
        if (not in_length or not out_length or
                inbound[0] * outbound[1] == inbound[1] * outbound[0]):
            path += f" L{corner[0]:g} {corner[1]:g}"
            continue
        bend = min(radius, in_length / 2, out_length / 2)
        entry = (corner[0] - inbound[0] / in_length * bend,
                 corner[1] - inbound[1] / in_length * bend)
        exit_point = (corner[0] + outbound[0] / out_length * bend,
                      corner[1] + outbound[1] / out_length * bend)
        path += (f" L{entry[0]:g} {entry[1]:g}"
                 f" Q{corner[0]:g} {corner[1]:g} {exit_point[0]:g} {exit_point[1]:g}")
    if len(compact) > 1:
        path += f" L{compact[-1][0]:g} {compact[-1][1]:g}"
    return path


def _wrapped_lines(label: str, width: float, max_lines: int = 3,
                   font_size: float = 13) -> list[str]:
    """Wrap by approximate glyph width so CJK labels stay within their shapes."""
    limit = max(8, int((width - 30) / (font_size * .54)))
    lines, current, units = [], "", 0
    for character in label.replace("\\n", "\n"):
        if character == "\n":
            if current.strip():
                lines.append(current.strip())
            current, units = "", 0
            continue
        size = 2 if unicodedata.east_asian_width(character) in {"F", "W"} else 1
        if current and units + size > limit:
            lines.append(current.strip())
            current, units = "", 0
        current += character
        units += size
    if current.strip():
        lines.append(current.strip())
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("… ") + "…"
    return lines


def render_preview(xml: str) -> str:
    model = parse_model(xml)
    root = model.find("root")
    if root is None:
        raise DiagramError("图表缺少 root 节点")
    cells = {cell.get("id"): cell for cell in root.findall("mxCell")}
    vertices = [cell for cell in cells.values() if cell.get("vertex") == "1" and cell.find("mxGeometry") is not None]
    if len(vertices) > 150:
        raise DiagramError("图表节点过多")

    def box(cell, seen=None):
        seen = seen or set()
        if cell.get("id") in seen:
            return (0, 0, 0, 0)
        seen.add(cell.get("id"))
        geom = cell.find("mxGeometry")
        if geom is None:
            return (0, 0, 0, 0)
        x, y = _number(geom.get("x")), _number(geom.get("y"))
        parent = cells.get(cell.get("parent"))
        if parent is not None and parent.get("vertex") == "1":
            px, py, _, _ = box(parent, seen)
            x, y = x + px, y + py
        return x, y, max(1, _number(geom.get("width"), 120)), max(1, _number(geom.get("height"), 50))

    boxes = {cell.get("id"): box(cell) for cell in vertices}
    if not boxes:
        raise DiagramError("图表没有可展示的节点")
    edge_data = []
    for cell in cells.values():
        if cell.get("edge") == "1" and cell.get("source") in boxes and cell.get("target") in boxes:
            edge_data.append((cell, _edge_points(cell, boxes[cell.get("source")], boxes[cell.get("target")])))
    all_points = [(x, y) for x, y, _, _ in boxes.values()]
    all_points.extend((x + w, y + h) for x, y, w, h in boxes.values())
    all_points.extend(point for _, path in edge_data for point in path)
    min_x = min(x for x, _ in all_points) - 42
    min_y = min(y for _, y in all_points) - 42
    max_x = max(x for x, _ in all_points) + 42
    max_y = max(y for _, y in all_points) + 42
    width, height = max_x - min_x, max_y - min_y
    edge_colors = list(dict.fromkeys(
        _color(_style(cell).get("strokeColor"), "#6B8BA0") for cell, _ in edge_data))
    marker_ids = {color: f"arrow-{index}" for index, color in enumerate(edge_colors)}
    markers = "".join(
        f'<marker id="{marker_ids[color]}" markerWidth="9" markerHeight="7" '
        'refX="8" refY="3.5" orient="auto">'
        f'<path d="M0 0 L8 3.5 L0 7 Z" fill="{color}"/></marker>'
        for color in edge_colors)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{min_x:g} {min_y:g} {width:g} {height:g}" width="{width:g}" height="{height:g}">',
           f'<defs>{markers}<filter id="node-shadow" x="-25%" y="-35%" width="150%" height="180%"><feDropShadow dx="0" dy="4" stdDeviation="5" flood-color="#213849" flood-opacity="0.15"/></filter></defs>',
           f'<rect x="{min_x:g}" y="{min_y:g}" width="{width:g}" height="{height:g}" fill="#fff"/>']
    group_ids = {cell.get("parent") for cell in vertices if cell.get("parent") in boxes}
    for cell in vertices:
        if cell.get("id") not in group_ids:
            continue
        x, y, w, h = boxes[cell.get("id")]
        style = _style(cell)
        fill = _color(style.get("fillColor"), "#f8fbff")
        stroke = _color(style.get("strokeColor"), "#bbd8e5")
        body_fill = _color(style.get("swimlaneFillColor"), fill)
        header_height = min(h, _number(style.get("startSize"), 36))
        dash = ' stroke-dasharray="4 4"' if style.get("dashed") == "1" else ""
        out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
                   f'rx="12" fill="{body_fill}" stroke="{stroke}" stroke-width="1.5"{dash}/>')
        if body_fill != fill and header_height:
            out.append(f'<path d="M{x+12:g} {y:g} H{x+w-12:g} Q{x+w:g} {y:g} {x+w:g} {y+12:g} '
                       f'V{y+header_height:g} H{x:g} V{y+12:g} Q{x:g} {y:g} {x+12:g} {y:g} Z" '
                       f'fill="{fill}"/>')
        label = clean_label(cell.get("value"))[:50]
        if label:
            font_color = _color(style.get("fontColor"), "#36596C")
            out.append(f'<text x="{x+14:g}" y="{y+23:g}" font-size="14" font-weight="bold" font-family="Arial, sans-serif" fill="{font_color}">{html.escape(label)}</text>')
    for cell, points in edge_data:
        path = _rounded_path(points)
        style = _style(cell)
        stroke = _color(style.get("strokeColor"), "#6B8BA0")
        dash = ' stroke-dasharray="5 4"' if style.get("dashed") == "1" else ""
        marker = (f' marker-end="url(#{marker_ids[stroke]})"'
                  if style.get("endArrow", "block") != "none" else "")
        weight = max(1, min(4, _number(style.get("strokeWidth"), 1.8)))
        out.append(f'<path d="{path}" fill="none" stroke="{stroke}" stroke-width="{weight:g}" stroke-linejoin="round"{marker}{dash}/>')
        label = clean_label(cell.get("value"))[:50]
        if label:
            lx, ly = _edge_label_anchor(points)
            label_color = _color(style.get("fontColor"), "#426579")
            out.append(f'<text x="{lx:g}" y="{ly:g}" text-anchor="middle" font-size="11" font-family="Arial, sans-serif" fill="{label_color}" paint-order="stroke" stroke="white" stroke-width="5">{html.escape(label)}</text>')
    for cell in vertices:
        if cell.get("id") in group_ids:
            continue
        x, y, w, h = boxes[cell.get("id")]
        style = _style(cell)
        fill = _color(style.get("fillColor"), "#e8f6fa")
        stroke = _color(style.get("strokeColor"), "#78bfd2")
        shape = style.get("shape", "")
        shadow = ' filter="url(#node-shadow)"' if style.get("shadow") == "1" else ""
        if "rhombus" in cell.get("style", "") or shape == "rhombus":
            points = f"{x+w/2:g},{y:g} {x+w:g},{y+h/2:g} {x+w/2:g},{y+h:g} {x:g},{y+h/2:g}"
            out.append(f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{shadow}/>')
        elif style.get("ellipse") == "1" or style.get("shape") == "ellipse" or "ellipse" in cell.get("style", ""):
            out.append(f'<ellipse cx="{x+w/2:g}" cy="{y+h/2:g}" rx="{w/2:g}" ry="{h/2:g}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{shadow}/>')
        else:
            out.append(f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{min(12,h/5):g}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"{shadow}/>')
        label = clean_label(cell.get("value"))[:160]
        if label:
            font_color = _color(style.get("fontColor"), "#244653")
            font_size = max(11, min(20, _number(style.get("fontSize"), 13)))
            font_weight = ' font-weight="bold"' if style.get("fontStyle") == "1" else ""
            is_diamond = "rhombus" in cell.get("style", "") or shape == "rhombus"
            lines = _wrapped_lines(label, w * (.72 if is_diamond else 1),
                                   2 if h < 70 else 4 if h >= 92 else 3, font_size)
            for index, line in enumerate(lines):
                yy = y + h / 2 + (index - (len(lines)-1)/2)*(font_size + 4) + 5
                out.append(f'<text x="{x+w/2:g}" y="{yy:g}" text-anchor="middle" font-size="{font_size:g}"{font_weight} font-family="Arial, sans-serif" fill="{font_color}">{html.escape(line)}</text>')
    out.append("</svg>")
    return "".join(out)
