"""Regression checks for compact flowcharts with branches and feedback loops."""

import json
import xml.etree.ElementTree as ET

from app.agents.drawing_layout import apply_layout
from app.agents.drawing_review import review_messages
from app.skills.drawing_engine import apply_operations, build_diagram
from app.skills.drawing_preview import _edge_points, render_preview
from app.plugins.diagram_agent.review import inspect_diagram


def test_large_flowchart_wraps_into_rows_and_routes_feedback_outside_nodes():
    nodes = [{"id": f"n{i}", "label": f"Step {i}",
              "kind": "decision" if i in {4, 12, 18} else "process"}
             for i in range(23)]
    nodes[0]["kind"] = "start"
    nodes[-1]["kind"] = "end"
    edges = [{"source": f"n{i}", "target": f"n{i+1}"} for i in range(22)]
    edges += [{"source": "n4", "target": "n1", "label": "retry"},
              {"source": "n12", "target": "n8", "label": "back"},
              {"source": "n18", "target": "n22", "label": "skip"}]
    result = build_diagram({"nodes": nodes, "edges": edges}, "flowchart")
    root = ET.fromstring(result.xml)
    cells = root.findall("./root/mxCell")
    positions = {cell.get("id"): cell.find("mxGeometry") for cell in cells
                 if cell.get("vertex") == "1"}
    xs = {int(geometry.get("x")) for geometry in positions.values()}
    ys = {int(geometry.get("y")) for geometry in positions.values()}
    assert len(xs) == 4
    assert len(ys) == 6
    assert max(ys) < 900
    assert int(root.get("pageWidth")) >= max(int(geometry.get("x")) + int(geometry.get("width"))
                                              for geometry in positions.values())
    assert int(root.get("pageHeight")) - max(int(geometry.get("y")) + int(geometry.get("height"))
                                               for geometry in positions.values()) < 100
    feedback = next(cell for cell in cells if cell.get("edge") == "1" and cell.get("value") == "retry")
    assert feedback.find("./mxGeometry/Array[@as='points']") is not None
    assert "exitY=0" in feedback.get("style")
    svg = render_preview(result.xml)
    assert "Step 22" in svg
    assert "retry" in svg
    assert svg.count("<path d=\"M") >= len(edges)
    view_box = ET.fromstring(svg).get("viewBox").split()
    width, height = map(float, view_box[2:])
    assert width / height > .8
    assert width / height < 2.5


def test_mindmap_preserves_parent_child_levels():
    plan = {"nodes": [{"id": name, "label": name} for name in
                      ("topic", "people", "process", "roles", "teams", "draft", "review")],
            "edges": [{"source": source, "target": target} for source, target in
                      (("topic", "people"), ("topic", "process"),
                       ("people", "roles"), ("people", "teams"),
                       ("process", "draft"), ("process", "review"))]}
    xml = build_diagram(plan, "mindmap").xml
    root = ET.fromstring(xml)
    cells = {cell.get("id"): cell for cell in root.findall("./root/mxCell")}
    x = {node_id: int(cell.find("mxGeometry").get("x")) for node_id, cell in cells.items()
         if cell.get("vertex") == "1"}
    assert x["people"] != x["process"]
    assert abs(x["roles"] - x["topic"]) > abs(x["people"] - x["topic"])
    assert abs(x["draft"] - x["topic"]) > abs(x["process"] - x["topic"])
    svg_root = ET.fromstring(render_preview(xml))
    assert len(svg_root.findall("{http://www.w3.org/2000/svg}path")) == 6


def test_mindmap_preview_routes_horizontal_ports_between_columns():
    edge = ET.Element("mxCell", {"style": "exitX=1;exitY=0.5;entryX=0;entryY=0.5;"})
    points = _edge_points(edge, (0, 0, 100, 50), (300, 100, 100, 50))
    assert points == [(100, 25), (200, 25), (200, 125), (300, 125)]


def test_layout_specialist_reorders_without_changing_graph_content():
    plan = {"nodes": [{"id": "a", "label": "入口", "group": "front"},
                      {"id": "b", "label": "服务", "group": "service"}],
            "edges": [{"source": "a", "target": "b"}],
            "groups": [{"id": "front", "label": "入口层"},
                       {"id": "service", "label": "服务层"}]}
    arranged, mode = apply_layout(
        '{"layout_mode":"layers","node_order":["b","a"],"group_order":["service","front"]}',
        plan, "flowchart")
    assert mode == "layers"
    assert [node["id"] for node in arranged["nodes"]] == ["b", "a"]
    assert arranged["edges"] == plan["edges"]
    assert [group["id"] for group in arranged["groups"]] == ["service", "front"]
    architecture = build_diagram(arranged, "architecture")
    assert "mxGraphModel" in architecture.xml
    assert "swimlaneFillColor=#FFFFFF" in architecture.xml
    assert 'fill="#FFFFFF"' in render_preview(architecture.xml)


def test_layout_order_changes_branch_positions_and_review_reports_canvas_size():
    plan = {"nodes": [{"id": node_id, "label": node_id, "kind": "process"}
                      for node_id in ("start", "left", "right", "finish")],
            "edges": [{"source": "start", "target": "left"},
                      {"source": "start", "target": "right"},
                      {"source": "left", "target": "finish"},
                      {"source": "right", "target": "finish"}]}
    arranged, _ = apply_layout(
        '{"layout_mode":"flow","node_order":["start","right","left","finish"]}',
        plan, "flowchart")
    result = build_diagram(arranged, "flowchart")
    cells = {cell.get("id"): cell for cell in ET.fromstring(result.xml).findall("./root/mxCell")}
    assert int(cells["right"].find("mxGeometry").get("y")) < int(
        cells["left"].find("mxGeometry").get("y"))
    svg = render_preview(result.xml)
    review = inspect_diagram(result.xml, svg, plan=arranged)
    _, _, width, height = map(float, ET.fromstring(svg).get("viewBox").split())
    assert (review["width"], review["height"]) == (round(width), round(height))
    assert review["width"] > 500
    evidence = json.loads(
        review_messages("检查排版", result.xml, "flowchart", review)[1]["content"])
    assert evidence["canvas"]["right"] == evidence["canvas"]["left"] + review["width"]


def test_semantic_palette_is_shared_by_editable_xml_and_preview():
    plan = {"nodes": [
        {"id": "start", "label": "Start", "kind": "start"},
        {"id": "choice", "label": "Choose", "kind": "decision"},
        {"id": "warning", "label": "Retry", "role": "warning"},
        {"id": "done", "label": "Done", "kind": "end"}],
        "edges": [{"source": "start", "target": "choice"},
                  {"source": "choice", "target": "warning"},
                  {"source": "choice", "target": "done"}],
        "visual": {"theme": "sage", "focus_id": "choice"}}
    result = build_diagram(plan, "flowchart")
    cells = {cell.get("id"): cell for cell in ET.fromstring(result.xml).findall("./root/mxCell")}
    styles = {node_id: cell.get("style") for node_id, cell in cells.items()}
    assert "fillColor=#356A5D" in styles["choice"]
    assert "fontColor=#FFFFFF" in styles["choice"]
    assert "fillColor=#F9E8E5" in styles["warning"]
    assert "fillColor=#E2F1E7" in styles["done"]
    svg = render_preview(result.xml)
    assert 'fill="#356A5D"' in svg
    assert 'fill="#FFFFFF">Choose</text>' in svg


def test_mindmap_branch_families_keep_node_and_edge_colors_together():
    plan = {"nodes": [{"id": node_id, "label": node_id} for node_id in
                      ("topic", "a", "a1", "b", "b1")],
            "edges": [{"source": "topic", "target": "a"},
                      {"source": "a", "target": "a1"},
                      {"source": "topic", "target": "b"},
                      {"source": "b", "target": "b1"}],
            "visual": {"theme": "indigo", "focus_id": "topic"}}
    xml = build_diagram(plan, "mindmap").xml
    cells = {cell.get("id"): cell for cell in ET.fromstring(xml).findall("./root/mxCell")}

    def color(cell):
        return next(part.split("=", 1)[1] for part in cell.get("style").split(";")
                    if part.startswith("strokeColor="))

    edges = {(cell.get("source"), cell.get("target")): cell for cell in cells.values()
             if cell.get("edge") == "1"}
    assert color(cells["a"]) == color(cells["a1"]) == color(edges["a", "a1"])
    assert color(cells["b"]) == color(cells["b1"]) == color(edges["b", "b1"])
    assert color(cells["a"]) != color(cells["b"])
    assert 'fontColor=#FFFFFF' in cells["topic"].get("style")


def test_ungrouped_flowchart_uses_consistent_reading_phases():
    plan = {"nodes": [{"id": f"n{i}", "label": f"Step {i}"} for i in range(12)],
            "edges": [{"source": f"n{i}", "target": f"n{i+1}"} for i in range(11)]}
    xml = build_diagram(plan, "flowchart").xml
    cells = {cell.get("id"): cell for cell in ET.fromstring(xml).findall("./root/mxCell")}

    def fill(node_id):
        return next(part.split("=", 1)[1] for part in cells[node_id].get("style").split(";")
                    if part.startswith("fillColor="))

    assert fill("n1") == fill("n2") == fill("n3")
    assert len({fill("n1"), fill("n5"), fill("n9")}) == 3
    assert 'shadow=1' in cells["n0"].get("style")


def test_mindmap_connections_are_unarrowed_in_xml_and_svg():
    plan = {"nodes": [{"id": "root", "label": "Topic"},
                      {"id": "branch", "label": "Branch"}],
            "edges": [{"source": "root", "target": "branch"}]}
    xml = build_diagram(plan, "mindmap").xml
    edge = next(cell for cell in ET.fromstring(xml).findall("./root/mxCell")
                if cell.get("edge") == "1")
    assert "endArrow=none" in edge.get("style")
    svg = ET.fromstring(render_preview(xml))
    connection = next(child for child in svg if child.tag.endswith("path"))
    assert "marker-end" not in connection.attrib


def test_group_colors_and_new_node_edit_keep_valid_styles():
    plan = {"nodes": [{"id": "a", "label": "First", "group": "phase"},
                      {"id": "b", "label": "Second", "group": "phase"}],
            "edges": [{"source": "a", "target": "b"}],
            "groups": [{"id": "phase", "label": "Phase"}]}
    xml = build_diagram(plan, "flowchart").xml
    cells = {cell.get("id"): cell for cell in ET.fromstring(xml).findall("./root/mxCell")}
    assert "fillColor=#DCEEF0" in cells["b"].get("style")
    updated = apply_operations(xml, [{"op": "add_node", "label": "Third"}])
    assert updated.nodes == 3
    assert "fillColor=#F1F6F8" in updated.xml


def test_review_flags_labels_that_preview_would_truncate():
    plan = {"nodes": [{"id": "long", "label": "Long label " * 14}], "edges": []}
    xml = build_diagram(plan, "flowchart").xml
    review = inspect_diagram(xml, render_preview(xml), plan=plan)
    assert any("标签在预览中被截断" in issue for issue in review["layout_issues"])


def test_flowchart_forks_downward_with_directed_arrows_and_separate_labels():
    plan = {"nodes": [
        {"id": "start", "label": "Start", "kind": "start"},
        {"id": "verify", "label": "Verify"},
        {"id": "choice", "label": "Approved?", "kind": "decision"},
        {"id": "pass", "label": "Prepare"},
        {"id": "fail", "label": "Correct"},
        {"id": "retry", "label": "Retry"},
        {"id": "finish", "label": "Finish", "kind": "end"},
    ], "edges": [
        {"source": "start", "target": "verify"},
        {"source": "verify", "target": "choice"},
        {"source": "choice", "target": "pass", "label": "Yes"},
        {"source": "choice", "target": "fail", "label": "No"},
        {"source": "fail", "target": "retry"},
        {"source": "retry", "target": "choice", "label": "Again"},
        {"source": "pass", "target": "finish"},
    ]}
    xml = build_diagram(plan, "flowchart").xml
    root = ET.fromstring(xml)
    cells = {cell.get("id"): cell for cell in root.findall("./root/mxCell")}
    coord = {node_id: (int(cells[node_id].find("mxGeometry").get("x")),
                       int(cells[node_id].find("mxGeometry").get("y")))
             for node_id in ("start", "choice", "pass", "fail", "finish")}
    assert coord["start"][1] < coord["choice"][1] < coord["pass"][1]
    assert coord["pass"][0] < coord["fail"][0]
    assert coord["finish"][1] > coord["pass"][1]
    edges = [cell for cell in cells.values() if cell.get("edge") == "1"]
    assert all("endArrow=block" in cell.get("style") for cell in edges)
    svg = ET.fromstring(render_preview(xml))
    labels = {element.text: float(element.get("x")) for element in svg.iter()
              if element.tag.endswith("text") and element.text in {"Yes", "No"}}
    assert labels["Yes"] < labels["No"]
    assert inspect_diagram(xml, render_preview(xml), plan=plan,
                           kind="flowchart")["approved"]
