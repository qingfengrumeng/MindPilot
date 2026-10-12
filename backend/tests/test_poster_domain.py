from app.core.model_preferences import write_preferences
"""Poster requests pass through the supervisor and keep mandatory uploaded imagery."""

import json
from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import Settings
from app.main import create_app
from app.plugins.poster_agent.render import render_html, visible_copy
from app.plugins.poster_agent.domain import run_domain
from app.runtime.protocol import TaskSpec


def test_renderer_escapes_copy_and_always_embeds_user_image():
    buffer = BytesIO()
    Image.new("RGB", (36, 36), "white").save(buffer, format="PNG")
    html = render_html({"title": "<script>alert(1)</script>", "brand": "用户品牌"}, [
        {"id": "f" * 32, "name": "活动二维码.png", "data": buffer.getvalue(), "qr": True},
    ], generated_image=buffer.getvalue())
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert f'data-asset-id="{"f" * 32}"' in html
    assert "data:image/png;base64," in html
    assert "扫码了解更多" in html
    assert 'class="generated-visual"' in html


def test_uploaded_photo_becomes_hero_and_qr_remains_separate():
    buffer = BytesIO()
    Image.new("RGB", (80, 80), "blue").save(buffer, format="PNG")
    data = buffer.getvalue()
    html = render_html({"title": "活动海报"}, [
        {"id": "a" * 32, "name": "主视觉.png", "data": data, "qr": False},
        {"id": "b" * 32, "name": "报名二维码.png", "data": data, "qr": True},
    ])
    assert f'data-asset-id="{"a" * 32}"' in html
    assert f'data-asset-id="{"b" * 32}"' in html
    assert 'class="generated-visual uploaded-visual"' in html
    assert html.count('class="asset qr"') == 1
    assert html.count('class="asset photo"') == 0

    logo_html = render_html({"asset_placements": {"a" * 32: "logo", "b" * 32: "qr"}}, [
        {"id": "a" * 32, "name": "unknown.png", "data": data, "qr": False},
        {"id": "b" * 32, "name": "unknown-2.png", "data": data, "qr": True},
    ])
    assert 'class="brand-logo"' in logo_html
    assert f'data-asset-id="{"a" * 32}"' in logo_html
    assert logo_html.count('class="asset qr"') == 1


def test_visible_copy_only_counts_text_that_is_rendered():
    assert "必须显示的完整句子" not in visible_copy({"title": "x" * 24 + "必须显示的完整句子"})
    assert "必须显示的完整句子" in visible_copy({"subtitle": "必须显示的完整句子"})


def test_poster_stream_analyzes_uploaded_pixels_before_design(tmp_path, monkeypatch):
    monkeypatch.setattr("app.api.routes.files.upload_image", lambda *args, **kwargs:
                        (_ for _ in ()).throw(AssertionError("海报素材不应调用远端文件接口")))
    env = tmp_path / "models.json"
    write_preferences(env, {'providers': {'deepseek': {'name': 'deepseek', 'runtimeProvider': 'deepseek', 'apiKey': 'test-key', 'configs': {'text': {'baseUrl': 'https://api.deepseek.com', 'model': 'deepseek-flash'}}}}, 'active': {'text': 'deepseek'}})
    for key in ("PROVIDER", "BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv(f"MINDPILOT_TEXT_{key}", raising=False)
    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'poster.db').as_posix()}",
                        jwt_secret="test-secret-longer-than-thirty-two-bytes-for-jwt",
                        allowed_origins=("http://localhost:5173",), model_config_path=env,
                        data_dir=tmp_path)
    app = create_app(settings)
    vision_calls = []

    def fake_model(config, messages):
        system = messages[0]["content"]
        if "素材理解 Agent" in system:
            blocks = messages[1]["content"]
            pictures = [block for block in blocks if block["type"] == "image_url"]
            assert len(pictures) == 1
            assert pictures[0]["image_url"]["url"].startswith("data:image/")
            vision_calls.append(config.model)
            return (json.dumps({"assets": [{"id": preview_id, "kind": "qr",
                                           "description": "一张黑白报名二维码",
                                           "visible_text": "", "suggested_placement": "qr",
                                           "reason": "应该完整展示，便于扫码"}]}, ensure_ascii=False), {})
        if "图稿质检 Agent" in system:
            return ('{"issues":[]}', {})
        if "主管 Agent" in system:
            assert "一张黑白报名二维码" in messages[1]["content"]
            return (json.dumps({"brand": "星河实验室", "goal": "发布活动", "audience": "学生",
                                "required_copy": ["扫码报名"], "visual_direction": "深蓝科技风",
                                "cta": "立即报名"}, ensure_ascii=False), {})
        assert "一张黑白报名二维码" in messages[1]["content"]
        return (json.dumps({"brand": "星河实验室", "title": "探索无限可能", "emphasis": "一起走向未来",
                            "subtitle": "参加我们的创意活动", "cta": "扫码报名",
                            "asset_placements": {preview_id: "qr"},
                            "features": [{"title": "探索", "detail": "发现新问题"},
                                         {"title": "设计", "detail": "释放创造力"},
                                         {"title": "协作", "detail": "共同向前"}]}, ensure_ascii=False), {})

    app.state.agent_runner.model_gateway.complete_fn = fake_model
    with TestClient(app) as client:
        client.post("/api/v1/auth/register", json={"username": "poster-user",
                                                   "password": "strong-password-123"})
        token = client.post("/api/v1/auth/login", json={"username": "poster-user",
                                                    "password": "strong-password-123"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        image = BytesIO()
        Image.new("RGB", (90, 90), "white").save(image, format="PNG")
        uploaded = client.post("/api/v1/files/poster-assets", headers=headers,
                               files={"file": ("素材.png", image.getvalue(), "image/png")})
        assert uploaded.status_code == 201, uploaded.text
        preview_id = uploaded.json()["previewId"]
        assert uploaded.json()["id"] == f"poster-local-{preview_id}"
        conversation = client.post("/api/v1/conversations", headers=headers,
                                   json={"title": "海报设计"}).json()
        response = client.post(f"/api/v1/conversations/{conversation['id']}/posters/stream",
                               headers=headers, json={"content": "制作活动海报，保留上传图片",
                                                      "skill": {"id": "poster", "label": "技术海报"},
                                                      "attachmentIds": [uploaded.json()["id"]],
                                                      "attachmentPreviewIds": [preview_id],
                                                      "attachmentNames": ["素材.png"]})
        assert response.status_code == 200, response.text
        events = [json.loads(line) for line in response.text.splitlines()]
        assert vision_calls == ["deepseek-flash"], response.text[-3000:]
        assert any(item["type"] == "trace" and any(
            stage["title"] == "素材理解 Agent · 看图与定位" for stage in item["trace"]["stages"])
                   for item in events)
        assert any(item["type"] == "trace" and any(
            stage["title"] == "视觉设计 Agent" for stage in item["trace"]["stages"])
                   for item in events)
        completed = next(item for item in events if item["type"] == "done")
        poster = completed["assistantMessage"]["metadata"]["poster"]
        assert poster["imageCount"] == 1
        for kind in ("htmlArtifactId", "pngArtifactId", "pdfArtifactId"):
            assert client.get(f"/api/v1/agent-artifacts/{poster[kind]}", headers=headers).status_code == 200
        assert client.get(f"/api/v1/agent-artifacts/{poster['pngArtifactId']}",
                          headers=headers).content.startswith(b"\x89PNG\r\n\x1a\n")
        assert client.get(f"/api/v1/agent-artifacts/{poster['pdfArtifactId']}",
                          headers=headers).content.startswith(b"%PDF")
        html = client.get(f"/api/v1/agent-artifacts/{poster['htmlArtifactId']}", headers=headers).text
        assert f'data-asset-id="{preview_id}"' in html
        assert 'class="asset qr"' in html
        user_id = client.get("/api/v1/auth/me", headers=headers).json()["id"]
        child = app.state.task_manager.children(completed["trace"]["runId"], user_id=user_id)[0]
        vision_request = next(row["detail"]["request_artifact_id"] for row in
                              app.state.task_manager.events(child.task_id, user_id=user_id)
                              if row["kind"] == "model_request" and
                              row["detail"].get("purpose") == "poster_asset_analysis")
        _, request_bytes = app.state.artifact_store.read(vision_request, user_id=user_id)
        assert b"base64," not in request_bytes
        assert b"inline_image" in request_bytes


def test_quality_feedback_reenters_design_at_most_three_times():
    class Context:
        def __init__(self):
            self.events = []
            self.design_calls = 0
            self.render_calls = 0

        def check_active(self):
            pass

        def event(self, kind, detail):
            self.events.append((kind, detail))

        def model(self, messages, *, purpose):
            if purpose == "poster_supervisor":
                return ('{"brand":"MindPilot","goal":"活动","required_copy":[]}', {})
            if purpose == "poster_visual_design":
                self.design_calls += 1
                if self.design_calls > 1:
                    assert messages[1]["content"].find("主视觉对比度") >= 0
                return ('{"title":"创意活动","emphasis":"即刻参加","brand":"MindPilot"}', {})
            if purpose == "poster_quality_review":
                return ('{"issues":[]}', {})
            raise AssertionError(purpose)

        def tool(self, name, arguments):
            assert name == "poster_render"
            self.render_calls += 1
            return {"html_artifact_id": "html", "png_artifact_id": "png",
                    "pdf_artifact_id": "pdf", "asset_count": 0,
                    "screenshot_evidence": {"width": 900, "height": 1280},
                    "issues": ([{"location": "视觉主体", "problem": "主视觉对比度不足",
                                 "suggestion": "提高亮度差"}] if self.render_calls < 3 else [])}

    context = Context()
    result = run_domain(TaskSpec(agent="poster_agent", goal="设计一张活动海报",
                                 inputs={"query": "设计一张活动海报"}), context)
    assert result.status == "completed"
    assert result.outputs["attempts"] == 3
    assert context.design_calls == context.render_calls == 3
    assert len([kind for kind, _ in context.events if kind == "poster_revision"]) == 2
