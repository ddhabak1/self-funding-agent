"""Turn an article into a top-notch, HD vertical YouTube Short.

v2 renderer: every frame is drawn with PIL (numpy backgrounds), so we get
full control over HD graphics and modern word-by-word animated captions
without relying on ffmpeg text filters or any external assets.

Design follows 2026 viral-Shorts best practices:
  - strong 1-3s hook, 15-40s length
  - big bold high-contrast captions, 2-3 words at a time, active word
    highlighted (watched-on-mute friendly)
  - constant motion: animated gradient + drifting glow, pop-in captions
  - top progress bar, loop-friendly ending

Output: media/<slug>/short.mp4 + meta.txt
"""
import asyncio
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config
from .brain import Brain

W, H = 1080, 1920
FPS = 24
VOICE = "en-US-GuyNeural"
GROUP_SIZE = 3

ACCENT = (94, 234, 212)      # teal highlight
WHITE = (248, 249, 252)
HANDLE = "@smarttechpickshq"

MEDIA_DIR = config.ROOT / "media"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]


def _font(size):
    for p in _FONT_CANDIDATES:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# --- article parsing -------------------------------------------------------
def read_post(path):
    txt = Path(path).read_text()
    body = txt.split("---", 2)[-1] if txt.startswith("---") else txt
    title = next((l[2:].strip() for l in body.splitlines()
                  if l.startswith("# ")), Path(path).stem)
    plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)
    plain = re.sub(r"[#*`>_]", "", plain)
    plain = re.split(r"Recommended gear|Disclosure:", plain)[0]
    return title, " ".join(plain.split())[:1800]


# --- scripting (Research/Content agent output) -----------------------------
def make_script(brain, title, body, buy_url=None):
    site = buy_url or f"{config.SITE_URL}{config.SITE_BASEURL}/"
    prompt = f"""You are a viral short-form video scriptwriter. Turn this article
into a punchy 25-38 second vertical SHORT that maximizes retention.
Title: "{title}"
Content: {body}

Rules: first line must be a 4-8 word scroll-stopping HOOK (curiosity/FOMO).
Spoken lines: short, punchy, <= 11 words, conversational, no filler.
Return strict JSON:
{{
 "hook": "4-8 word hook",
 "lines": ["6-8 spoken lines"],
 "cta": "one line: check the link in the description",
 "yt_title": "<=90 char title with a hook",
 "yt_description": "2-3 lines; include the buy link {site}; note some links may be affiliate",
 "hashtags": ["8-10 hashtags without # symbol"]
}}"""
    data = brain.think(prompt, as_json=True)
    if not isinstance(data, dict) or "lines" not in data:
        data = {
            "hook": title[:60],
            "lines": ["Here's what you actually need to know.",
                      "It's faster, smarter, and worth the upgrade.",
                      "But there's a catch most people miss."],
            "cta": "Full guide and top picks in the description.",
            "yt_title": title[:90],
            "yt_description": f"Buy here: {site}\nSome links may be affiliate.",
            "hashtags": ["tech", "gadgets", "shorts", "techtok"],
        }
    return data


# --- voice -----------------------------------------------------------------
async def _tts(text, out):
    import edge_tts
    await edge_tts.Communicate(text, VOICE, rate="+8%").save(str(out))


def synth(text, out):
    asyncio.run(_tts(text, out))
    return _duration(out)


def _duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 1.5


# --- timeline --------------------------------------------------------------
def _build_timeline(script, tmp):
    """Create caption groups, synth audio per group, return groups + durations."""
    units = []
    units.append({"text": script["hook"], "emph": True})
    for ln in script["lines"]:
        units.append({"text": ln, "emph": False})
    units.append({"text": script.get("cta", "Link in the description!"),
                  "emph": True})

    groups, audio_files, t = [], [], 0.0
    gi = 0
    for u in units:
        words = u["text"].split()
        # split a line into small caption groups of GROUP_SIZE words
        for i in range(0, len(words), GROUP_SIZE):
            chunk = words[i:i + GROUP_SIZE]
            mp3 = tmp / f"g{gi}.mp3"
            dur = synth(" ".join(chunk), mp3) + 0.06
            groups.append({"words": chunk, "start": t, "dur": dur,
                           "emph": u["emph"]})
            audio_files.append(mp3)
            t += dur
            gi += 1
    return groups, audio_files, t


# --- background (numpy, animated) ------------------------------------------
_BG_W, _BG_H = W // 2, H // 2  # render bg at half-res then upscale (fast+smooth)
_yy, _xx = np.mgrid[0:_BG_H, 0:_BG_W].astype(np.float32)


def _bg_frame(t, total):
    # vertical gradient between two slowly shifting deep colors
    phase = t / max(total, 1)
    top = np.array([14, 18, 38]) + np.array([10, 4, 22]) * math.sin(phase * 3.14)
    bot = np.array([30, 22, 66]) + np.array([8, 10, 18]) * math.cos(phase * 2.0)
    v = (_yy / _BG_H)[..., None]
    img = top[None, None, :] * (1 - v) + bot[None, None, :] * v

    # drifting radial accent glow -> constant motion
    cx = _BG_W * (0.5 + 0.32 * math.sin(t * 0.6))
    cy = _BG_H * (0.4 + 0.28 * math.cos(t * 0.45))
    d2 = (_xx - cx) ** 2 + (_yy - cy) ** 2
    glow = np.exp(-d2 / (2 * (_BG_W * 0.55) ** 2)).astype(np.float32)
    acc = np.array(ACCENT, dtype=np.float32)
    img += glow[..., None] * acc[None, None, :] * 0.28

    img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img, "RGB").resize((W, H), Image.BILINEAR)
    return im


def _vignette_mask():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    m = np.clip(1.0 - 0.45 * d2, 0.35, 1.0)
    return m[..., None]


_VIGNETTE = _vignette_mask()


def _apply_vignette(im):
    arr = np.asarray(im).astype(np.float32) * _VIGNETTE
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# --- caption rendering -----------------------------------------------------
def _draw_caption(im, words, active_idx, scale, emph):
    draw = ImageDraw.Draw(im)
    base = 118 if emph else 96
    size = max(40, int(base * scale))
    font = _font(size)
    gap = int(size * 0.28)

    widths = [draw.textlength(w, font=font) for w in words]
    total_w = sum(widths) + gap * (len(words) - 1)
    # wrap to max 2 lines if too wide
    max_w = W - 150
    lines, cur, cur_w = [], [], 0.0
    for w, ww in zip(words, widths):
        add = ww + (gap if cur else 0)
        if cur_w + add > max_w and cur:
            lines.append((cur, cur_w))
            cur, cur_w = [], 0.0
            add = ww
        cur.append((w, ww))
        cur_w += add
    if cur:
        lines.append((cur, cur_w))

    line_h = size + int(size * 0.2)
    total_h = line_h * len(lines)
    y = int(H * 0.46) - total_h // 2
    idx = 0
    asc = font.getbbox("Ag")[3]
    for ln, lw in lines:
        x = (W - lw) // 2
        for w, ww in ln:
            color = ACCENT if idx == active_idx else WHITE
            draw.text((x, y), w, font=font, fill=color,
                      stroke_width=max(3, size // 18), stroke_fill=(0, 0, 0))
            x += ww + gap
            idx += 1
        y += line_h


def _draw_chrome(im, progress):
    draw = ImageDraw.Draw(im)
    # top progress bar
    draw.rectangle([0, 0, W, 12], fill=(0, 0, 0))
    draw.rectangle([0, 0, int(W * progress), 12], fill=ACCENT)
    # brand kicker
    kf = _font(40)
    draw.text((60, 70), "SMART TECH PICKS", font=kf, fill=ACCENT,
              stroke_width=3, stroke_fill=(0, 0, 0))
    # handle bottom
    hf = _font(38)
    tw = draw.textlength(HANDLE, font=hf)
    draw.text(((W - tw) // 2, H - 150), HANDLE, font=hf, fill=(210, 220, 235),
              stroke_width=3, stroke_fill=(0, 0, 0))


def _render_frames(groups, total, frames_dir):
    n = int(math.ceil(total * FPS))
    gi = 0
    for f in range(n):
        t = f / FPS
        while gi + 1 < len(groups) and t >= groups[gi + 1]["start"]:
            gi += 1
        g = groups[gi]
        local = t - g["start"]
        # word highlight timing (even split across group duration)
        wi = min(len(g["words"]) - 1, int(local / g["dur"] * len(g["words"])))
        # pop-in scale for first 0.13s of a group
        pop = min(1.0, local / 0.13)
        scale = 0.86 + 0.14 * (1 - (1 - pop) ** 2)

        im = _bg_frame(t, total)
        im = _apply_vignette(im)
        _draw_caption(im, g["words"], wi, scale, g["emph"])
        _draw_chrome(im, min(1.0, t / total))
        im.save(frames_dir / f"f{f:05d}.png")
    return n


# --- assembly --------------------------------------------------------------
def make_thumbnail(script, slug):
    """Render one static hook frame as a standalone marketing image (for
    Instagram/Pinterest posts, or as a video thumbnail) — reuses the exact
    same drawing primitives as the video so it looks consistent."""
    outdir = MEDIA_DIR / slug
    outdir.mkdir(parents=True, exist_ok=True)
    words = script.get("hook", "").split() or ["New", "find"]
    im = _bg_frame(0.6, 3.0)   # a lively mid-animation background frame
    im = _apply_vignette(im)
    _draw_caption(im, words, len(words) - 1, 1.0, True)
    out = outdir / "thumbnail.jpg"
    im.convert("RGB").save(out, quality=90)
    return out


def build_from_script(script, slug):
    outdir = MEDIA_DIR / slug
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        groups, audio_files, total = _build_timeline(script, tmp)

        # concat narration audio
        listf = tmp / "a.txt"
        listf.write_text("".join(f"file '{p}'\n" for p in audio_files))
        narration = tmp / "narration.mp3"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                        "-i", str(listf), "-c", "copy", str(narration)],
                       check=True, capture_output=True)

        frames_dir = tmp / "frames"
        frames_dir.mkdir()
        _render_frames(groups, total, frames_dir)

        out = outdir / "short.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(FPS),
             "-i", str(frames_dir / "f%05d.png"), "-i", str(narration),
             "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", str(out)],
            check=True, capture_output=True)
    _write_meta(outdir, script)
    return out


def build_short(post_path):
    title, body = read_post(post_path)
    script = make_script(Brain(), title, body)
    return build_from_script(script, Path(post_path).stem)


def _write_meta(outdir, script):
    tags = " ".join("#" + re.sub(r"[^0-9A-Za-z]", "", h)
                    for h in script.get("hashtags", [])
                    if re.sub(r"[^0-9A-Za-z]", "", h))
    meta = (f"TITLE:\n{script.get('yt_title', '')}\n\n"
            f"DESCRIPTION:\n{script.get('yt_description', '')}\n\n{tags}\n")
    (outdir / "meta.txt").write_text(meta)


if __name__ == "__main__":
    import sys
    if "--mock" in sys.argv:
        demo = {
            "hook": "Stop overpaying for slow WiFi",
            "lines": ["Wi-Fi 7 is a massive speed jump.",
                      "It uses multi-link operation for zero lag.",
                      "Perfect for 8K streaming and gaming.",
                      "But you need the right router."],
            "cta": "Full guide and top picks in the description.",
            "yt_title": "Stop Overpaying For Slow WiFi",
            "yt_description": "Full guide: link below.",
            "hashtags": ["WiFi7", "TechTok", "Shorts", "Gadgets"],
        }
        print("Built ->", build_from_script(demo, "demo-mock"))
    else:
        posts = sorted(config.POSTS_DIR.glob("*.md"), reverse=True)
        target = sys.argv[1] if len(sys.argv) > 1 else str(posts[0])
        print("Built ->", build_short(target))
