"""Safe, deterministic HTML poster renderer and browser exports."""

from __future__ import annotations

import base64
from html import escape
from io import BytesIO
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageStat

WIDTH, HEIGHT = 900, 1280
PALETTES = {
    "aurora": ("#07132c", "#102b60", "#59dff9", "#edf8ff"),
    "violet": ("#110d29", "#35246c", "#b7a0ff", "#f5f0ff"),
    "ember": ("#21120e", "#683326", "#ffc08a", "#fff4e9"),
    "forest": ("#061c1d", "#124b4a", "#92e4c1", "#edfff4"),
}


def _text(value, limit=120):
    return escape(str(value or "")[:limit], quote=True)


def _headline_size(*parts: str) -> int:
    def units(value: str) -> float:
        return sum(1.0 if ord(char) > 127 else 0.58 for char in value)
    return max(42, min(78, int(735 / max(1, *(units(part) for part in parts)))))


def visible_copy(design: dict) -> str:
    """Text that the poster template actually places on the canvas."""
    parts = [
        str(design.get("brand") or "MindPilot")[:25],
        str(design.get("title") or "让创意被看见")[:24],
        str(design.get("emphasis") or "让未来更近")[:24],
        str(design.get("subtitle") or "把想法变成值得分享的作品。")[:65],
        str(design.get("eyebrow") or "探索 · 思考 · 创造")[:32],
        str(design.get("tag") or "CREATE · EXPLORE MORE")[:45],
        str(design.get("hero_word") or "AI")[:7],
        str(design.get("cta") or "即刻探索")[:18],
    ]
    labels = design.get("hero_labels")
    if isinstance(labels, list):
        parts.extend(str(item)[:9] for item in labels[:3])
    features = design.get("features")
    if isinstance(features, list):
        for item in features[:3]:
            if isinstance(item, dict):
                parts.extend((str(item.get("title") or "")[:13],
                              str(item.get("detail") or "")[:24]))
    return "".join(parts)


def _image_src(data: bytes, name: str) -> str:
    with Image.open(BytesIO(data)) as source:
        if source.format not in {"PNG", "JPEG", "GIF", "WEBP"}:
            raise ValueError("海报素材必须是 PNG、JPEG、GIF 或 WebP 图片")
        if source.width * source.height > 25_000_000:
            raise ValueError("海报素材尺寸过大，请缩小后重新上传")
        source.thumbnail((1024, 1024) if name == "generated.png" else (560, 560))
        output = BytesIO()
        if (source.format == "PNG" or source.mode in {"RGBA", "LA"}
                or "transparency" in source.info or "二维码" in name.lower() or "qr" in name.lower()):
            source.save(output, format="PNG", optimize=True)
            mime = "image/png"
        else:
            source.convert("RGB").save(output, format="JPEG", quality=87, optimize=True)
            mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(output.getvalue()).decode('ascii')}"


def render_html(design: dict, assets: list[dict], generated_image: bytes | None = None) -> str:
    palette = PALETTES.get(design.get("palette"), PALETTES["aurora"])
    background, mid, accent, foreground = palette
    title = _text(design.get("title") or "让创意被看见", 24)
    emphasis = _text(design.get("emphasis") or "让未来更近", 24)
    subtitle = _text(design.get("subtitle") or "把想法变成值得分享的作品。", 65)
    eyebrow = _text(design.get("eyebrow") or "探索 · 思考 · 创造", 32)
    brand = _text(design.get("brand") or "MindPilot", 25)
    cta = _text(design.get("cta") or "即刻探索", 18)
    tag = _text(design.get("tag") or "CREATE · EXPLORE MORE", 45)
    features = [item for item in (design.get("features") or [])[:3]
                if isinstance(item, dict)] if isinstance(design.get("features"), list) else []
    while len(features) < 3:
        features.append({"title": ["探索问题", "激发创意", "协作创作"][len(features)], "detail": "从想法出发，持续向前"})
    feature_html = "".join(f'<div class="feature"><b>{_text(item.get("title"), 13)}</b>'
                           f'<span>{_text(item.get("detail"), 24)}</span></div>' for item in features)
    # The designer can place analyzed assets, while every upload remains mandatory.
    placements = design.get("asset_placements")
    placements = placements if isinstance(placements, dict) else {}
    logo_asset = next((asset for asset in assets
                       if placements.get(asset["id"]) == "logo" and not asset.get("qr")), None)
    hero_asset = None
    if generated_image is None:
        hero_asset = next((asset for asset in assets if placements.get(asset["id"]) == "hero"
                           and asset is not logo_asset and not asset.get("qr")), None)
        if hero_asset is None and not placements and len(assets) <= 2:
            hero_asset = next((asset for asset in assets if not asset.get("qr")
                               and asset is not logo_asset), None)
    asset_html = []
    for index, asset in enumerate(assets):
        if asset is hero_asset or asset is logo_asset:
            continue
        src = _image_src(asset["data"], asset["name"])
        label = _text(asset["name"], 32)
        role = "qr" if asset.get("qr") else "photo"
        asset_html.append(f'<figure class="asset {role}" data-asset-id="{_text(asset["id"], 32)}">'
                          f'<img src="{src}" alt="{label}"><figcaption>{"扫码了解更多" if role == "qr" else label}</figcaption></figure>')
    assets_class = f" has-assets asset-count-{min(len(asset_html), 8)}" if asset_html else ""
    if len(asset_html) > 4:
        assets_class += " many-assets"
    hero_word = _text(design.get("hero_word") or "AI", 7)
    labels = design.get("hero_labels") or ["探索发现", "深度思考", "协作创作"]
    if not isinstance(labels, list):
        labels = ["探索发现", "深度思考", "协作创作"]
    labels = [_text(labels[index] if index < len(labels) else ["探索发现", "深度思考", "协作创作"][index], 9)
              for index in range(3)]
    headline_size = _headline_size(str(design.get("title") or ""), str(design.get("emphasis") or ""))
    generated_visual = (f'<img class="generated-visual" src="{_image_src(generated_image, "generated.png")}" alt="生成的海报视觉元素">'
                        if generated_image else "")
    if hero_asset is not None:
        generated_visual = (f'<img class="generated-visual uploaded-visual" '
                            f'data-asset-id="{_text(hero_asset["id"], 32)}" '
                            f'src="{_image_src(hero_asset["data"], hero_asset["name"])}" '
                            f'alt="{_text(hero_asset["name"], 32)}">')
    brand_mark = (f'<img class="brand-logo" data-asset-id="{_text(logo_asset["id"], 32)}" '
                  f'src="{_image_src(logo_asset["data"], logo_asset["name"])}" '
                  f'alt="{_text(logo_asset["name"], 32)}">') if logo_asset else '<i class="brand-mark"></i>'
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width={WIDTH},initial-scale=1"><title>{title} · 海报</title>
<style>
@page {{size:{WIDTH}px {HEIGHT}px;margin:0}}
* {{box-sizing:border-box}} html,body {{margin:0;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden}}
body {{font-family:"Microsoft YaHei","Noto Sans CJK SC",Arial,sans-serif;color:{foreground};background:{background}}}
.poster {{position:relative;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;padding:58px 68px 54px;
 background:radial-gradient(ellipse 65% 44% at 58% 57%,{mid} 0%,transparent 78%),
 linear-gradient(155deg,{background} 3%,{mid} 52%,{background} 100%)}}
.grid {{position:absolute;inset:0;opacity:.22;background-image:linear-gradient({accent}44 1px,transparent 1px),linear-gradient(90deg,{accent}44 1px,transparent 1px);background-size:46px 46px;mask-image:linear-gradient(to bottom,transparent,#000 19%,#000 80%,transparent)}}
.border {{position:absolute;inset:18px;border:1px solid {accent}38;pointer-events:none}}
.top,.bottom {{position:relative;z-index:3;display:flex;align-items:center;justify-content:space-between}}
.brand {{display:flex;align-items:center;gap:15px;font-size:25px;font-weight:800;letter-spacing:.01em}}
.brand-mark {{width:32px;height:32px;border:2px solid {accent};border-radius:50%;box-shadow:0 0 20px {accent};position:relative}}
.brand-mark:after {{content:"";position:absolute;right:-3px;top:-2px;width:9px;height:9px;background:{accent};border-radius:50%;box-shadow:0 0 12px {accent}}}
.brand-logo {{display:block;width:40px;height:40px;object-fit:contain;filter:drop-shadow(0 0 8px {accent}99)}}
.top-tag,.footnote {{color:{accent};font-size:12px;letter-spacing:.24em}}
.copy {{position:relative;z-index:3;margin-top:86px;max-width:760px}}
.eyebrow {{font-size:15px;font-weight:700;letter-spacing:.3em;color:{accent};margin:0 0 20px}}
h1 {{font-size:{headline_size}px;line-height:1.08;letter-spacing:-.045em;margin:0;font-weight:900;text-shadow:0 3px 15px #0005}}
h1 span {{display:block;max-width:750px;overflow-wrap:anywhere}}
h1 .emphasis {{background:linear-gradient(110deg,{foreground} 5%,{accent} 74%,#8d94b2);color:transparent;background-clip:text;-webkit-background-clip:text}}
.subtitle {{font-size:21px;line-height:1.6;color:{foreground};opacity:.88;margin:24px 0 0;max-width:740px}}
.hero {{position:absolute;z-index:1;top:510px;left:50%;transform:translateX(-50%);width:590px;height:540px}}
.orbit {{position:absolute;border:1px solid {accent}70;border-radius:50%;width:600px;height:330px;left:0;top:90px;transform:rotate(-24deg)}}
.orbit.second {{transform:rotate(28deg);width:560px;height:290px;left:20px;top:115px;opacity:.7}}
.halo {{position:absolute;width:385px;height:385px;left:102px;top:44px;border-radius:50%;background:radial-gradient(circle,{accent}77 0%,{accent}25 55%,transparent 72%);filter:blur(24px)}}
.orb {{position:absolute;width:344px;height:344px;left:123px;top:64px;border-radius:50%;border:1px solid {accent}bb;
 background:radial-gradient(circle at 36% 27%,{accent} 0%,{mid} 64%,{background} 80%);
 box-shadow:inset -20px -25px 34px #010514,0 0 27px {accent}aa,0 0 90px {accent}5a;display:flex;align-items:center;justify-content:center}}
.orb:after {{content:"";position:absolute;inset:29px;border:1px solid {accent}8a;border-radius:50%}}
.orb strong {{font-size:91px;line-height:1;color:white;text-shadow:0 0 22px {accent},0 0 60px {accent}}}
.generated-visual {{position:absolute;inset:20px;width:calc(100% - 40px);height:calc(100% - 40px);object-fit:cover;border-radius:50%;z-index:1}}
.uploaded-visual {{object-fit:contain;filter:drop-shadow(0 0 16px {accent}80)}}
.dot {{position:absolute;width:9px;height:9px;border-radius:50%;background:#b8ffff;box-shadow:0 0 13px {accent},0 0 24px {accent}}}
.d1 {{left:26px;top:194px}} .d2 {{right:4px;top:122px}} .d3 {{left:100px;bottom:23px}} .d4 {{right:57px;bottom:62px}}
.pill {{position:absolute;padding:13px 19px;border:1px solid {accent}95;border-radius:22px;background:{mid}cc;font-size:14px;font-weight:700;white-space:nowrap}}
.p1 {{left:-15px;top:108px}} .p2 {{right:-30px;top:210px}} .p3 {{left:8px;bottom:34px}}
.assets {{position:absolute;z-index:4;top:834px;left:68px;right:68px;display:flex;gap:12px;align-items:end;justify-content:flex-end}}
.asset {{display:flex;flex-direction:column;gap:5px;margin:0;padding:7px;border:1px solid {accent}80;background:{background}ee;border-radius:9px;max-width:150px;min-width:0}}
.asset img {{width:128px;height:128px;object-fit:contain;background:#fff;border-radius:4px}}
.asset.qr {{max-width:176px}} .asset.qr img {{width:160px;height:160px}}
.asset figcaption {{font-size:10px;text-align:center;color:#d3e6f5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.asset-count-2 .assets,.asset-count-3 .assets,.asset-count-4 .assets {{top:830px;justify-content:center}}
.asset-count-2 .asset,.asset-count-3 .asset,.asset-count-4 .asset {{flex:0 1 168px}}
.many-assets .assets {{top:740px;left:185px;right:68px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;align-items:stretch}}
.many-assets .asset,.many-assets .asset.qr {{width:100%;max-width:none;padding:5px;min-height:112px;justify-content:center}}
.many-assets .asset img,.many-assets .asset.qr img {{width:100%;height:88px;object-fit:contain}}
.many-assets .asset.qr img {{height:104px}}
.bottom {{position:absolute;left:68px;right:68px;bottom:54px;display:block}}
.features {{border-top:1px solid {accent}48;padding:24px 0 29px;display:grid;grid-template-columns:repeat(3,1fr);gap:22px}}
.feature {{min-width:0;border-left:1px solid {accent};padding:3px 0 3px 21px;display:flex;flex-direction:column;gap:8px}}
.feature b {{font-size:18px}} .feature span {{font-size:12px;color:{foreground};opacity:.78;line-height:1.45}}
.bottom-row {{display:flex;align-items:center;justify-content:space-between}}
.cta {{padding:15px 23px;border-radius:7px;background:linear-gradient(105deg,#fff,{accent});color:{background};font-size:15px;font-weight:900;box-shadow:0 0 24px {accent}70}}
.has-assets .hero {{top:470px;transform:translateX(-50%) scale(.76)}}
.many-assets .hero {{top:440px;transform:translateX(-50%) scale(.52)}}
</style></head><body><main class="poster{assets_class}"><div class="grid"></div><div class="border"></div>
<header class="top"><div class="brand">{brand_mark}{brand}</div><div class="top-tag">{tag}</div></header>
<section class="copy"><p class="eyebrow">{eyebrow}</p><h1><span>{title}</span><span class="emphasis">{emphasis}</span></h1><p class="subtitle">{subtitle}</p></section>
<section class="hero" aria-label="视觉主体"><div class="halo"></div><div class="orbit"></div><div class="orbit second"></div><div class="orb"><strong>{hero_word}</strong>{generated_visual}</div><i class="dot d1"></i><i class="dot d2"></i><i class="dot d3"></i><i class="dot d4"></i><span class="pill p1">{labels[0]} ✦</span><span class="pill p2">{labels[1]} ↗</span><span class="pill p3">{labels[2]} &lt;/&gt;</span></section>
<section class="assets">{''.join(asset_html)}</section>
<footer class="bottom"><div class="features">{feature_html}</div><div class="bottom-row"><small class="footnote">MINDPILOT / INTELLIGENCE FOR EXPLORERS</small><span class="cta">{cta} ↗</span></div></footer>
</main></body></html>'''


def browser_binary() -> str:
    for candidate in [shutil.which("msedge"),
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      shutil.which("chrome"), shutil.which("chromium"),
                      r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      "/usr/bin/chromium", "/usr/bin/chromium-browser",
                      "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("海报渲染需要本机安装 Chrome 或 Edge")


def export_browser(html: str) -> tuple[bytes, bytes]:
    browser = browser_binary()
    with TemporaryDirectory(prefix="mindpilot-poster-") as directory:
        root = Path(directory)
        source = root / "poster.html"
        png = root / "poster.png"
        pdf = root / "poster.pdf"
        source.write_text(html, encoding="utf-8")
        common = [browser, "--headless=new", "--disable-gpu", "--disable-gpu-sandbox",
                  "--disable-features=VizDisplayCompositor", "--no-sandbox", "--hide-scrollbars",
                  "--no-first-run", "--disable-extensions", "--allow-file-access-from-files",
                  f"--window-size={WIDTH},{HEIGHT}",
                  "--force-device-scale-factor=1"]
        for index, extra in enumerate(([f"--screenshot={png}"], [f"--print-to-pdf={pdf}", "--print-to-pdf-no-header"])):
            completed = subprocess.run([*common, f"--user-data-dir={root / f'profile-{index}'}",
                                        *extra, source.as_uri()], capture_output=True,
                                       timeout=45, check=False)
            if completed.returncode != 0:
                raise RuntimeError("浏览器渲染海报失败：" + completed.stderr.decode("utf-8", "replace")[-400:])
        if not png.is_file() or not pdf.is_file():
            raise RuntimeError("浏览器没有生成完整的海报截图和 PDF")
        result_png, result_pdf = png.read_bytes(), pdf.read_bytes()
        with Image.open(BytesIO(result_png)) as image:
            if image.size[0] < WIDTH or image.size[1] < HEIGHT:
                raise RuntimeError("海报截图尺寸异常")
        return result_png, result_pdf


def inspect_screenshot(png: bytes, design: dict, assets: list[dict]) -> list[dict]:
    """QA agent uses actual screenshot pixels and known element positions."""
    issues = []
    with Image.open(BytesIO(png)) as image:
        rgb = image.convert("RGB")
        overall = ImageStat.Stat(rgb.resize((90, 128)))
        if max(overall.stddev) < 3:
            issues.append({"location": "整张海报", "problem": "渲染结果几乎是纯色空白",
                           "suggestion": "检查浏览器渲染并重做视觉版式", "critical": True})
        if rgb.size[0] < WIDTH or rgb.size[1] < HEIGHT:
            issues.append({"location": "画布", "problem": "截图尺寸不完整", "suggestion": "按 900×1280 重新渲染"})
        samples = ImageStat.Stat(rgb.crop((80, 520, 820, 1000))).stddev
        if max(samples) < 12:
            issues.append({"location": "视觉主体", "problem": "截图中间区域过于单调", "suggestion": "增强主视觉与背景的明度差"})
    if len(str(design.get("title", ""))) > 14:
        issues.append({"location": "主标题第一行", "problem": "标题可能超出单行宽度", "suggestion": "将主标题压缩到 14 字以内"})
    if len(str(design.get("emphasis", ""))) > 14:
        issues.append({"location": "主标题第二行", "problem": "强调句可能超出单行宽度", "suggestion": "将强调句压缩到 14 字以内"})
    return issues


def screenshot_evidence(png: bytes) -> dict:
    """Small spatial/color measurements the text QA model can actually inspect."""
    with Image.open(BytesIO(png)) as image:
        rgb = image.convert("RGB")
        regions = {
            "heading": (70, 170, 830, 450),
            "hero": (140, 500, 760, 1050),
            "footer": (65, 1060, 835, 1260),
        }
        measurements = {}
        for name, box in regions.items():
            stat = ImageStat.Stat(rgb.crop(box))
            measurements[name] = {"mean_rgb": [round(value) for value in stat.mean],
                                  "contrast_stddev": [round(value) for value in stat.stddev]}
        return {"width": rgb.width, "height": rgb.height, "regions": measurements}
