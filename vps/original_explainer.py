"""Deterministic, original scientific explainers used only for explicit graphic beats.

These are not generated stock clips: every frame is drawn from a checked scene
specification, so a reviewer can see exactly which mechanism is being claimed.
"""
from __future__ import annotations

import math
import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class ExplainerError(RuntimeError):
    pass


def _probe_video(path: Path) -> dict:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=45)
    if p.returncode:
        raise ExplainerError(f"ffprobe failed: {p.stderr[-500:]}")
    data = json.loads(p.stdout)
    stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not stream:
        raise ExplainerError("original explainer has no video stream")
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    duration = float(stream.get("duration") or data.get("format", {}).get("duration") or 0)
    if width < 1920 or height < 1080 or duration < 1:
        raise ExplainerError(f"invalid original explainer output: {width}x{height}, {duration:.2f}s")
    return {"width": width, "height": height, "duration": duration, "codec": stream.get("codec_name")}

W, H, FPS = 3840, 2160, 30
BG = (8, 12, 20)
TEXT = (239, 244, 251)
GOLD = (255, 177, 40)
GOLD_DARK = (141, 82, 12)
BONE = (222, 231, 239)
DISC = (91, 186, 222)
DISC_DARK = (20, 76, 107)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(name, size=size)


def _arrow(draw: ImageDraw.ImageDraw, a: tuple[int, int], b: tuple[int, int], color: tuple[int, int, int] = GOLD, width: int = 24) -> None:
    draw.line([a, b], fill=color, width=width)
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    for sign in (-1, 1):
        p = (b[0] - int(48 * math.cos(angle + sign * .55)), b[1] - int(48 * math.sin(angle + sign * .55)))
        draw.line([b, p], fill=color, width=width)


def _spine_frame(progress: float, mode: str) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    title = "EARTH GRAVITY COMPRESSES DISCS" if mode in {"compression", "recompression"} else "MICROGRAVITY LETS DISCS EXPAND"
    d.text((220, 150), title, font=_font(94, True), fill=TEXT)
    d.text((220, 270), "ORIGINAL SCIENTIFIC EXPLAINER", font=_font(46, True), fill=GOLD)
    x = W // 2
    top = 515
    direction = 1 if mode == "compression" else -1
    # 0.5 is visibly neutral, compression = narrow discs, expansion = wide discs.
    if mode == "compression": factor = 1.15 - .48 * progress
    elif mode == "recompression": factor = .67 + .48 * progress
    else: factor = .67 + .48 * progress
    disc_h = int(126 * factor)
    vertebra_h, vertebra_w = 188, 640
    centers = []
    y = top
    for n in range(6):
        d.rounded_rectangle((x - vertebra_w // 2, y, x + vertebra_w // 2, y + vertebra_h), radius=68, fill=BONE, outline=(117, 136, 153), width=15)
        d.ellipse((x - 175, y + 35, x + 175, y + 148), fill=(195, 208, 219))
        centers.append(y + vertebra_h // 2)
        if n < 5:
            dy = y + vertebra_h
            d.rounded_rectangle((x - 260, dy, x + 260, dy + disc_h), radius=disc_h // 2, fill=DISC, outline=DISC_DARK, width=14)
            # Visible fluid swell / squeeze marks.
            for offset in (-120, -40, 40, 120):
                radius = int(18 + 14 * (1 - factor if mode == "compression" else factor - .5))
                d.ellipse((x + offset - radius, dy + disc_h // 2 - radius, x + offset + radius, dy + disc_h // 2 + radius), fill=(169, 226, 245))
            y = dy + disc_h
        else:
            y += vertebra_h
    if mode == "compression":
        _arrow(d, (x - 760, top + 230), (x - 760, top + 780), GOLD)
        _arrow(d, (x + 760, top + 230), (x + 760, top + 780), GOLD)
        d.text((x - 1030, 1780), "DOWNWARD LOAD  •  DISCS NARROW", font=_font(72, True), fill=GOLD)
    elif mode == "recompression":
        _arrow(d, (x - 760, top + 230), (x - 760, top + 780), GOLD)
        _arrow(d, (x + 760, top + 230), (x + 760, top + 780), GOLD)
        d.text((x - 1070, 1780), "EARTH GRAVITY  •  SPINE RECOMPRESSES", font=_font(72, True), fill=GOLD)
    else:
        _arrow(d, (x - 760, top + 780), (x - 760, top + 230), GOLD)
        _arrow(d, (x + 760, top + 780), (x + 760, top + 230), GOLD)
        d.text((x - 1040, 1780), "PRESSURE FADES  •  DISCS EXPAND", font=_font(72, True), fill=GOLD)
    return im


def _height_frame(progress: float) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((220, 150), "HEIGHT MEASUREMENT IN ORBIT", font=_font(94, True), fill=TEXT)
    d.text((220, 270), "ORIGINAL EXPLAINER • ASTRONAUT SCALE", font=_font(46, True), fill=GOLD)
    base = 1810
    x = 1500
    # A calibrated vertical scale, with a moving astronaut silhouette.
    d.line((2640, 470, 2640, base), fill=TEXT, width=24)
    for i in range(0, 15):
        y = base - i * 90
        tick = 100 if i % 5 else 190
        d.line((2640 - tick, y, 2640 + 30, y), fill=TEXT, width=14)
    extension = int(105 * progress)
    head_y = 750 - extension
    d.ellipse((x - 160, head_y, x + 160, head_y + 320), fill=BONE)
    d.rounded_rectangle((x - 220, head_y + 300, x + 220, 1400), radius=150, fill=(229, 238, 245), outline=(117, 136, 153), width=15)
    d.line((x - 210, 1080, x - 610, 1220), fill=BONE, width=150)
    d.line((x + 210, 1080, x + 610, 960), fill=BONE, width=150)
    d.line((x - 110, 1390, x - 210, base), fill=BONE, width=170)
    d.line((x + 110, 1390, x + 210, base), fill=BONE, width=170)
    d.line((x + 230, head_y + 150, 2640, head_y + 150), fill=GOLD, width=22)
    d.text((2730, head_y + 85), "+ UP TO 3%", font=_font(76, True), fill=GOLD)
    d.text((560, 1900), "CALIBRATED HEIGHT REFERENCE", font=_font(72, True), fill=TEXT)
    return im


def _microgravity_frame(progress: float) -> Image.Image:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.text((220, 150), "MICROGRAVITY REMOVES DOWNWARD LOAD", font=_font(86, True), fill=TEXT)
    d.text((220, 270), "ORIGINAL EXPLAINER • FIXED HEIGHT REFERENCE", font=_font(46, True), fill=GOLD)
    # Cabin reference grid stays fixed while the suited figure drifts upward.
    for x in range(340, W - 260, 320):
        d.line((x, 500, x, 1830), fill=(38, 54, 69), width=8)
    for y in range(540, 1840, 260):
        d.line((300, y, W - 260, y), fill=(38, 54, 69), width=8)
    d.line((3000, 480, 3000, 1840), fill=TEXT, width=22)
    for i in range(0, 13):
        y = 1820 - i * 100
        d.line((2860 if i % 5 else 2780, y, 3030, y), fill=TEXT, width=13)
    drift = int(150 * math.sin(progress * math.pi))
    cx, head_y = 1640, 720 - drift
    d.ellipse((cx - 145, head_y, cx + 145, head_y + 290), fill=(191, 209, 222), outline=(91, 126, 149), width=14)
    d.rounded_rectangle((cx - 245, head_y + 265, cx + 245, head_y + 970), radius=150, fill=(228, 237, 244), outline=(117, 136, 153), width=15)
    d.line((cx - 220, head_y + 560, cx - 670, head_y + 430), fill=BONE, width=150)
    d.line((cx + 220, head_y + 560, cx + 660, head_y + 720), fill=BONE, width=150)
    d.line((cx - 120, head_y + 930, cx - 260, head_y + 1380), fill=BONE, width=170)
    d.line((cx + 120, head_y + 930, cx + 300, head_y + 1320), fill=BONE, width=170)
    d.line((cx + 245, head_y + 145, 3000, head_y + 145), fill=GOLD, width=22)
    _arrow(d, (980, 1500), (980, 1040), GOLD)
    d.text((520, 1900), "BODY FLOATS • CABIN SCALE STAYS FIXED", font=_font(70, True), fill=GOLD)
    return im


def _frame(kind: str, progress: float) -> Image.Image:
    if kind == "spine_compression":
        return _spine_frame(progress, "compression")
    if kind == "spine_expansion":
        return _spine_frame(progress, "expansion")
    if kind == "spine_recompression":
        return _spine_frame(progress, "recompression")
    if kind == "height_measurement":
        return _height_frame(progress)
    if kind == "astronaut_microgravity":
        return _microgravity_frame(progress)
    raise ExplainerError(f"unsupported original explainer kind: {kind}")


def render_original_explainer(spec: dict, output: Path, duration: float) -> dict:
    kind = str(spec.get("kind") or "")
    if kind not in {"spine_compression", "spine_expansion", "spine_recompression", "height_measurement", "astronaut_microgravity"}:
        raise ExplainerError("original_explainer.kind is required and unsupported")
    if duration < 1.5:
        raise ExplainerError("original explainer duration must be at least 1.5 seconds")
    frames = output.parent / f"{output.stem}-frames"
    frames.mkdir(parents=True, exist_ok=True)
    total = max(2, int(round(duration * FPS)))
    for i in range(total):
        # Ease-in/out makes the causal movement visibly deliberate.
        p = i / (total - 1)
        eased = p * p * (3 - 2 * p)
        _frame(kind, eased).save(frames / f"frame-{i:05d}.png")
    tmp = output.with_suffix(".part.mp4")
    # The PNGs are the 4K masters.  The worker cache is deliberately made
    # Full HD here: it is the renderer's delivery intermediate and avoids an
    # unnecessary 4K H.264 encoder spike on the small persistent worker.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", str(frames / "frame-%05d.png"),
           "-vf", "scale=1920:1080:flags=lanczos", "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
    if run.returncode or not tmp.is_file():
        raise ExplainerError(f"original explainer render failed: {run.stderr[-1000:]}")
    tmp.replace(output)
    media = _probe_video(output)
    return {"kind": "original_explainer", "origin": "deterministic_local_graphic", "path": str(output), **media}
