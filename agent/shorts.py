"""Turn a published article into a vertical YouTube Short (video + metadata).

Pipeline: article -> Gemini script -> edge-tts voiceover (per line) ->
Pillow text cards -> ffmpeg segments -> concatenated 1080x1920 MP4.

Produces: media/<slug>/short.mp4 and media/<slug>/meta.txt
Free stack, no external API keys required.
"""
import asyncio
import json
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config
from .brain import Brain

W, H = 1080, 1920
BG_TOP = (11, 16, 32)
BG_BOTTOM = (24, 32, 64)
ACCENT = (94, 234, 212)
WHITE = (245, 245, 245)

MEDIA_DIR = config.ROOT / "media"

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
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


# --- scripting -------------------------------------------------------------
def make_script(brain, title, body):
    site = f"{config.SITE_URL}{config.SITE_BASEURL}/"
    prompt = f"""Turn this article into a punchy ~35-second vertical SHORT.
Title: "{title}"
Content: {body}

Return strict JSON:
{{
 "hook": "a 5-8 word scroll-stopping opening line",
 "lines": ["6 to 7 short spoken caption lines, each <= 12 words, punchy"],
 "cta": "one line telling viewers to check the link in bio/description",
 "yt_title": "<= 90 char YouTube title with a hook, no hashtags",
 "yt_description": "2-3 lines. Mention full guide link {site} and that links may be affiliate.",
 "hashtags": ["6-10 relevant hashtags without the # symbol"]
}}"""
    data = brain.think(prompt, as_json=True)
    if not isinstance(data, dict) or "lines" not in data:
        # offline / parse fallback
        data = {
            "hook": title,
            "lines": [title, "Here's what you need to know.",
                      "Check the full guide for details."],
            "cta": "Full guide + picks in the description.",
            "yt_title": title[:90],
            "yt_description": f"Full guide: {site}\nSome links may be affiliate.",
            "hashtags": ["tech", "gadgets", "shorts"],
        }
    return data


# --- voice -----------------------------------------------------------------
async def _tts(text, out):
    import edge_tts
    voice = "en-US-AriaNeural"
    await edge_tts.Communicate(text, voice).save(str(out))


def synth(text, out):
    asyncio.run(_tts(text, out))
    return _duration(out)


def _duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 2.0


# --- rendering -------------------------------------------------------------
def _bg():
    img = Image.new("RGB", (W, H), BG_TOP)
    top, bot = BG_TOP, BG_BOTTOM
    for y in range(H):
        t = y / H
        img.paste(tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)),
                  (0, y, W, y + 1))
    return img


def _wrap(draw, text, font, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def card(text, out, kicker="SMART TECH PICKS", accent=False):
    img = _bg()
    d = ImageDraw.Draw(img)
    f_big = _font(76)
    f_kick = _font(38)

    d.text((70, 120), kicker, font=f_kick, fill=ACCENT)
    d.rectangle([70, 180, 320, 188], fill=ACCENT)

    lines = _wrap(d, text, f_big, W - 160)
    line_h = 96
    total = len(lines) * line_h
    y = (H - total) // 2
    for ln in lines:
        w = d.textlength(ln, font=f_big)
        color = ACCENT if accent else WHITE
        d.text(((W - w) // 2, y), ln, font=f_big, fill=color)
        y += line_h

    d.text((70, H - 130), "youtube.com/@smarttechpickshq",
           font=_font(30), fill=(150, 160, 180))
    img.save(out)


def _segment(png, mp3, out, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(mp3),
         "-c:v", "libx264", "-tune", "stillimage", "-c:a", "aac",
         "-b:a", "192k", "-pix_fmt", "yuv420p", "-t", f"{dur:.2f}",
         "-vf", f"scale={W}:{H}", str(out)],
        check=True, capture_output=True)


def build_short(post_path):
    title, body = read_post(post_path)
    brain = Brain()
    script = make_script(brain, title, body)

    slug = Path(post_path).stem
    outdir = MEDIA_DIR / slug
    outdir.mkdir(parents=True, exist_ok=True)

    segments = []
    blocks = [(script["hook"], True)] + [(l, False) for l in script["lines"]]
    blocks.append((script.get("cta", "Link in the description!"), True))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for i, (text, accent) in enumerate(blocks):
            if not text.strip():
                continue
            mp3 = tmp / f"a{i}.mp3"
            png = tmp / f"c{i}.png"
            dur = synth(text, mp3) + 0.35
            card(text, png, accent=accent)
            seg = tmp / f"s{i}.mp4"
            _segment(png, mp3, seg, dur)
            segments.append(seg)

        listfile = tmp / "list.txt"
        listfile.write_text("".join(f"file '{s}'\n" for s in segments))
        out_mp4 = outdir / "short.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listfile),
             "-c", "copy", str(out_mp4)],
            check=True, capture_output=True)

    _write_meta(outdir, script)
    return outdir / "short.mp4"


def _write_meta(outdir, script):
    tags = " ".join(
        "#" + re.sub(r"[^0-9A-Za-z]", "", h) for h in script.get("hashtags", [])
        if re.sub(r"[^0-9A-Za-z]", "", h)
    )
    meta = (
        f"TITLE:\n{script.get('yt_title', '')}\n\n"
        f"DESCRIPTION:\n{script.get('yt_description', '')}\n\n{tags}\n"
    )
    (outdir / "meta.txt").write_text(meta)


if __name__ == "__main__":
    import sys
    posts = sorted(config.POSTS_DIR.glob("*.md"), reverse=True)
    target = sys.argv[1] if len(sys.argv) > 1 else str(posts[0])
    print("Building short for:", target)
    print("Done ->", build_short(target))
