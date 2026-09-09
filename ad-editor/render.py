"""
render.py — takes an (ideally human-reviewed) EDL JSON + your talking-head
video and renders the final ad: burned-in phrase captions with accent
colors, zoom-punches, b-roll cutaways, and text "slide" beats.

Usage:
    python render.py --video talking_head.mp4 --edl edl.json --out output/final.mp4

Design notes (read this before extending):
- Captions are rendered as an .ass subtitle file (libass), one Dialogue
  event per caption phrase, with inline {\\c&Hxxxxxx&} color overrides for
  accent words. This is why captions can have per-word color without
  chaining dozens of drawtext filters.
- Zoom-punch is done via a per-frame time-varying `scale` (eval=frame)
  followed by a centered `crop` back to the canvas size. It reevaluates
  every frame, which is fine for ad-length clips but not for long video.
- Cutaways and slides are both "full-frame overlays for a time window" —
  cutaways use your b-roll video files, slides use a PNG generated on the
  fly with Pillow. Both are composited with `overlay=enable=between(t,s,e)`.
- chord_label beats are rendered as a second, smaller ASS style so they
  don't need their own filter chain.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ffmpeg_util import resolve_ffmpeg
from validate_edl import EDLValidationError, validate_edl

CANVAS_W, CANVAS_H = 1080, 1920
WARM_TINT_KELVIN = 4500  # ffmpeg colortemperature default is 6500 (neutral); lower = warmer
FLARE_WIDTH = CANVAS_W * 2  # wide canvas the flare pans across during its beat
FLASH_COLOR = "FFB84D"  # warm amber, matches the "warm color-wash" language in the style bible

# Picture-in-picture (a "pip" beat): a small bordered card in a corner while
# the talking head stays fully visible underneath — for things like an
# ebook cover or a course-catalog screen recording, per reference ads where
# these are shown as an inset card with a caption label, never a full-frame
# cutaway.
#
# Width was 460 with the card starting at x=580 — for a CENTER-framed
# talking head (this crop keeps the subject roughly centered, unlike the
# reference ad where the subject sits further left), the subject's own
# face/hair reaches about x=760 on a 1080-wide canvas. A card starting at
# x=580 sat directly on top of the face. Narrowed + pushed further right so
# the card clears the measured face boundary with margin, using the actual
# empty background space beside the head instead of assuming it's there.
PIP_WIDTH = 280
PIP_MARGIN = 24
PIP_BORDER = 8
PIP_POSITIONS = {  # (x, y) of the card's top-left corner, pre-border
    "top-right": (CANVAS_W - PIP_WIDTH - PIP_MARGIN, 130),
    "top-left": (PIP_MARGIN, 130),
    "bottom-right": (CANVAS_W - PIP_WIDTH - PIP_MARGIN, None),  # y computed per-card height
}
_PIP_LABEL_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Black.ttf"


def wrap_text_to_width(text: str, font_path: str, font_size: int, max_width_px: int) -> list[str]:
    """Greedy word-wrap using actual rendered glyph widths (PIL), not a
    guessed characters-per-line count — needed so a PIP label wraps to fit
    the card it sits under instead of assuming it'll fit on one line."""
    font = ImageFont.truetype(font_path, font_size)
    measurer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        w = measurer.textbbox((0, 0), candidate, font=font)[2]
        if w <= max_width_px or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def hex_to_ass_color(hex_rgb: str, alpha: int = 0) -> str:
    hex_rgb = hex_rgb.lstrip("#")
    r, g, b = hex_rgb[0:2], hex_rgb[2:4], hex_rgb[4:6]
    return f"&H{alpha:02X}{b}{g}{r}&"


def get_source_duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def get_source_dimensions(path: str) -> tuple[int, int]:
    """width, height of an image or video file, via ffprobe (works for both).
    Plain "ffprobe" is fine here (no libass/freetype needed for probing)."""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    w, h = result.stdout.strip().split(",")
    return int(w), int(h)


COLORS = {
    None: hex_to_ass_color("FFFFFF"),
    "gold": hex_to_ass_color("FFD400"),
    "red": hex_to_ass_color("FF2A2A"),
}
CHORD_LABEL_COLOR = hex_to_ass_color("FFFFFF")


def build_ass(edl: dict, out_path: str, font_name: str = "Arial Black"):
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {CANVAS_W}
PlayResY: {CANVAS_H}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{font_name},72,&H00FFFFFF,&H00000000,&H00000000,1,0,1,4,0,5,60,60,260,1
Style: Chord,{font_name},48,{CHORD_LABEL_COLOR},&H00000000,&H00000000,1,0,1,3,0,2,60,60,700,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    def fmt_time(t: float) -> str:
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h:d}:{m:02d}:{s:05.2f}"

    lines = [header]
    for cap in edl.get("captions", []):
        text_parts = []
        for w in cap["words"]:
            color = COLORS.get(w.get("accent"), COLORS[None])
            text_parts.append(f"{{\\c{color}}}{w['text']}")
        text = " ".join(text_parts)
        lines.append(
            f"Dialogue: 0,{fmt_time(cap['start'])},{fmt_time(cap['end'])},Caption,,0,0,0,,{text}\n"
        )

    for beat in edl.get("beats", []):
        if beat["type"] == "chord_label":
            lines.append(
                f"Dialogue: 1,{fmt_time(beat['start'])},{fmt_time(beat['end'])},Chord,,0,0,0,,{beat['text']}\n"
            )

    Path(out_path).write_text("".join(lines), encoding="utf-8")


# Fallback fonts to try (in order) when --font isn't passed or can't be
# loaded. Bare filenames like "DejaVuSans-Bold.ttf" almost never resolve on
# macOS (PIL needs a real path) and silently fall back to PIL's tiny bitmap
# default font — which quietly breaks the "huge central number" slide look.
# These are real, commonly-present paths, checked in order.
_FALLBACK_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Supplemental/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # common on Linux
]


def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [font_path] if font_path else []
    candidates += _FALLBACK_FONT_PATHS
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise RuntimeError(
        "No usable .ttf font found for slide text (tried: "
        f"{candidates}). Pass --font /path/to/font.ttf, or install one of "
        "the fallback paths above. Falling back to PIL's tiny bitmap font "
        "would silently break the slide's 'huge central number' look, so "
        "this is a hard error instead."
    )


def make_slide_png(beat: dict, out_path: str, font_path: str = None):
    img = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    big_font = _load_font(font_path, 220)
    small_font = _load_font(font_path, 70)

    text = beat.get("text", "")
    bbox = draw.textbbox((0, 0), text, font=big_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((CANVAS_W - tw) / 2, (CANVAS_H - th) / 2 - 80), text, font=big_font, fill="white")

    subtext = beat.get("subtext")
    if subtext:
        bbox2 = draw.textbbox((0, 0), subtext, font=small_font)
        tw2 = bbox2[2] - bbox2[0]
        draw.text(((CANVAS_W - tw2) / 2, (CANVAS_H + th) / 2 + 20), subtext, font=small_font, fill="white")

    img.convert("RGB").save(out_path)


def make_flare_png(out_path: str):
    """
    Synthetic anamorphic-style lens flare: a bright warm core, a horizontal
    streak (the classic "anamorphic bar"), and a few small fading "ghost"
    circles trailing off to one side — drawn once on a canvas TWICE the
    video's width, as RGBA with alpha proportional to brightness (so the
    black background is fully transparent). render.py pans a CANVAS_W-wide
    crop window across this image over the beat's duration and composites
    it with a normal `overlay` (same technique already used for slides/
    cutaways) — brightness-as-alpha makes it read as light passing over the
    lens without needing an additive blend mode. (An earlier version used
    `blend=all_mode=screen` directly on an opaque RGB source; ffmpeg blends
    "screen" per YUV plane by default, which screens the chroma planes too
    and produced a strong, wrong magenta cast across the WHOLE frame in
    testing — not just near the bright spot. Plain alpha-overlay sidesteps
    that colorspace issue entirely, using the same compositing path already
    proven correct for every other overlay in this file.)
    """
    W, H = FLARE_WIDTH, CANVAS_H
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx, cy = W // 2, int(H * 0.38)
    WARM = (255, 235, 200)  # warm-white core color, alpha carries the falloff

    # Radial core glow: concentric circles, brightest (most opaque) at center.
    max_r = 260
    for r in range(max_r, 0, -4):
        t = 1 - (r / max_r)
        a = int(255 * (t ** 2.2))
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*WARM, a))

    # Horizontal anamorphic streak through the core.
    streak_half_h = 10
    for dx in range(-W // 2, W // 2):
        dist = abs(dx) / (W / 2)
        a = int(255 * max(0.0, 1 - dist) ** 3)
        if a <= 2:
            continue
        x = cx + dx
        if 0 <= x < W:
            draw.line([(x, cy - streak_half_h), (x, cy + streak_half_h)],
                      fill=(255, 240, 210, a))

    # Ghost circles trailing toward one corner (classic multi-element lens look).
    dir_x, dir_y = -1, 1  # trail toward lower-left
    for dist, radius, bright in [(300, 40, 120), (520, 25, 90), (760, 60, 70), (980, 18, 110)]:
        gx = cx + dir_x * dist
        gy = cy + dir_y * int(dist * 0.35)
        for r in range(radius, 0, -3):
            t = 1 - (r / radius)
            a = int(bright * (t ** 2))
            draw.ellipse([gx - r, gy - r, gx + r, gy + r], fill=(255, 245, 225, a))

    img.save(out_path)


def build_zoom_expr(beats: list) -> str:
    """Chain zoom_punch beats into a single time-based scale-factor expression."""
    expr = "1"
    for b in beats:
        if b["type"] != "zoom_punch":
            continue
        s, e = b["start"], b["end"]
        zf, zt = b.get("zoom_from", 1.0), b.get("zoom_to", 1.15)
        ramp = f"({zf}+({zt}-{zf})*(t-{s})/({e}-{s}))"
        expr = f"if(between(t,{s},{e}),{ramp},{expr})"
    return expr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--edl", required=True)
    ap.add_argument("--out", default="output/final.mp4")
    ap.add_argument("--font", default=None, help="Path to a .ttf for slide text (defaults to DejaVuSans-Bold)")
    ap.add_argument("--broll", default=None,
                     help="broll_manifest.json, used only to double-check cutaway \"source\" "
                          "files exist in your manifest (optional but recommended)")
    ap.add_argument("--skip-validation", action="store_true",
                     help="render even if the EDL fails validation (not recommended — you'll "
                          "likely get a confusing ffmpeg error instead of a clear one)")
    args = ap.parse_args()

    edl = json.loads(Path(args.edl).read_text(encoding="utf-8"))

    if not args.skip_validation:
        broll_manifest = None
        if args.broll:
            broll_manifest = json.loads(Path(args.broll).read_text(encoding="utf-8"))
        try:
            validate_edl(edl, broll_manifest)
        except EDLValidationError as e:
            print(f"[render] {e}", file=sys.stderr)
            print(
                "[render] Refusing to render an invalid EDL — fix the problems above, "
                "or pass --skip-validation to render anyway.", file=sys.stderr,
            )
            sys.exit(1)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    work = Path(args.out).parent / "_work"
    work.mkdir(exist_ok=True)

    ass_path = work / "captions.ass"
    build_ass(edl, str(ass_path))

    fps = edl.get("video_meta", {}).get("fps", 30)

    beats = edl.get("beats", [])
    cutaways = [b for b in beats if b["type"] == "cutaway"]
    slides = [b for b in beats if b["type"] == "slide"]
    flashes = [b for b in beats if b["type"] == "flash"]
    flares = [b for b in beats if b["type"] == "flare"]
    pips = [b for b in beats if b["type"] == "pip"]

    # Render slide beats to PNGs
    slide_files = []
    for i, b in enumerate(slides):
        png_path = work / f"slide_{i}.png"
        make_slide_png(b, str(png_path), args.font)
        slide_files.append((b, str(png_path)))

    flare_png = None
    if flares:
        flare_png = work / "flare.png"
        make_flare_png(str(flare_png))

    zoom_expr = build_zoom_expr(beats)

    # ---- Build ffmpeg command ----
    IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

    inputs = ["-i", args.video]
    for b in cutaways:
        if Path(b["source"]).suffix.lower() in IMAGE_EXTS:
            # A static image cutaway (e.g. the ebook cover) — without -loop
            # ffmpeg treats it as a single-frame "video" that ends
            # immediately, which would make the overlay disappear after one
            # frame. -loop 1 holds it for the beat's duration instead.
            inputs += ["-itsoffset", str(b["start"]), "-loop", "1",
                       "-t", str(b["end"] - b["start"]), "-i", b["source"]]
        else:
            inputs += ["-itsoffset", str(b["start"]), "-i", b["source"]]
    for b, png_path in slide_files:
        inputs += ["-loop", "1", "-i", png_path]
    for b in flashes:
        dur = b["end"] - b["start"]
        inputs += [
            "-itsoffset", str(b["start"]),
            "-f", "lavfi", "-i",
            f"color=c=0x{FLASH_COLOR}:s={CANVAS_W}x{CANVAS_H}:d={dur}:r={fps}",
        ]
    for b in flares:
        if b.get("source"):
            # Real flare footage (e.g. a bought/team transition asset) is
            # timed via `setpts` in the filter graph instead of -itsoffset —
            # see the filter-building loop below for why (itsoffset shifts
            # raw packet timestamps before the speed-up filter runs, and the
            # two don't compose the way you'd guess).
            inputs += ["-i", b["source"]]
        else:
            inputs += ["-itsoffset", str(b["start"]), "-loop", "1", "-t", str(b["end"] - b["start"]), "-i", str(flare_png)]
    for b in pips:
        if Path(b["source"]).suffix.lower() in IMAGE_EXTS:
            inputs += ["-itsoffset", str(b["start"]), "-loop", "1",
                       "-t", str(b["end"] - b["start"]), "-i", b["source"]]
        else:
            inputs += ["-itsoffset", str(b["start"]), "-i", b["source"]]
    # Optional real SFX file on ANY beat (e.g. a whoosh/transition sound, or
    # a highlight ding on an accented caption word) — mixed into the audio
    # track at the beat's start time. Plain audio input, no -itsoffset
    # needed here since timing is applied via `adelay` in the filter graph.
    sfx_beats = [b for b in beats if b.get("sfx")]
    for b in sfx_beats:
        inputs += ["-i", b["sfx"]]

    filter_parts = []
    # base: zoom-punch on main video, scaled to canvas
    filter_parts.append(
        f"[0:v]scale=w='iw*({zoom_expr})':h='ih*({zoom_expr})':eval=frame,"
        f"crop={CANVAS_W}:{CANVAS_H}:'(iw-{CANVAS_W})/2':'(ih-{CANVAS_H})/2'[base]"
    )

    cur = "base"
    input_idx = 1
    for i, b in enumerate(cutaways):
        scaled = f"cut{i}"
        out_label = f"v{i}"
        tint_filter = ""
        if b.get("tint") == "warm":
            # style bible calls for "warm color-wash" on some cutaways.
            # colortemperature lowers Kelvin from its 6500K default to push
            # the image warmer (more orange/red, less blue) without touching
            # composition — cheap and reversible if the look needs tuning.
            tint_filter = f",colortemperature=temperature={WARM_TINT_KELVIN}"
        elif b.get("tint") not in (None, ""):
            print(
                f"[render] WARNING: cutaway beat has unknown tint={b['tint']!r} "
                "(only \"warm\" is implemented) — ignoring.", file=sys.stderr,
            )
        filter_parts.append(
            f"[{input_idx}:v]scale={CANVAS_W}:{CANVAS_H}:force_original_aspect_ratio=increase,"
            f"crop={CANVAS_W}:{CANVAS_H}{tint_filter}[{scaled}]"
        )
        filter_parts.append(
            f"[{cur}][{scaled}]overlay=enable='between(t,{b['start']},{b['end']})'[{out_label}]"
        )
        cur = out_label
        input_idx += 1

    for i, (b, _) in enumerate(slide_files):
        out_label = f"s{i}"
        filter_parts.append(
            f"[{cur}][{input_idx}:v]overlay=enable='between(t,{b['start']},{b['end']})'[{out_label}]"
        )
        cur = out_label
        input_idx += 1

    # Flash beats: a brief opacity-ramped color wash at a cut point (pattern
    # interrupt #4 in the style bible). Composited last / on top, since a
    # flash reads as a transition cue over whatever shot is currently
    # showing (talking head, cutaway, or slide) rather than something that
    # needs to sit "under" them.
    for i, b in enumerate(flashes):
        dur = b["end"] - b["start"]
        half = dur / 2
        colored = f"flashsrc{i}"
        out_label = f"f{i}"
        filter_parts.append(
            f"[{input_idx}:v]format=yuva420p,"
            f"fade=t=in:st=0:d={half}:alpha=1,"
            f"fade=t=out:st={half}:d={dur - half}:alpha=1[{colored}]"
        )
        filter_parts.append(
            f"[{cur}][{colored}]overlay=enable='between(t,{b['start']},{b['end']})'[{out_label}]"
        )
        cur = out_label
        input_idx += 1

    # Flare beats: a synthetic camera-flare panning across frame. The source
    # PNG is drawn once at FLARE_WIDTH (2x canvas) as RGBA with alpha
    # proportional to brightness (see make_flare_png); panning a CANVAS_W
    # crop window across it over the beat's duration is what makes it sweep
    # through frame, composited with a plain `overlay` — the same technique
    # already used for slides/cutaways, chosen after `blend=screen` (an
    # earlier attempt) turned out to operate per-YUV-plane and wash the
    # whole frame magenta instead of adding light only where the flare is
    # actually bright.
    for i, b in enumerate(flares):
        dur = b["end"] - b["start"]
        out_label = f"fl{i}"
        if b.get("source"):
            # Real flare footage: these assets (e.g. a bought transition
            # pack) are typically a slow few-second black -> bloom -> black
            # cycle, meant to be sped up into a quick punchy flash rather
            # than played at native speed. `setpts` both compresses the
            # clip to the beat's duration AND shifts it to start at the
            # beat's global start time in one expression — see the note by
            # the corresponding -i in the inputs list above for why this
            # replaces -itsoffset here instead of combining with it.
            #
            # Alpha comes from the footage's own luma (alphamerge), not a
            # blend mode: black areas (the footage's "off" state) become
            # fully transparent and only the bright bloom shows through,
            # composited with a plain `overlay` — the same reliable pattern
            # used everywhere else in this file. An earlier synthetic flare
            # tried `blend=all_mode=screen` directly and washed the WHOLE
            # frame magenta; converting to rgb24 around the blend didn't
            # fix it either (the output was byte-for-byte identical, which
            # means the per-YUV-plane theory was wrong too — never
            # diagnosed further since the alpha/overlay route sidesteps the
            # whole class of bug and is proven correct elsewhere).
            orig_dur = get_source_duration(b["source"])
            factor = dur / orig_dur
            sped = f"flrsped{i}"
            alpha = f"flralpha{i}"
            rgba = f"flrrgba{i}"
            filter_parts.append(
                f"[{input_idx}:v]setpts=({factor})*PTS+{b['start']}/TB,split=2[{sped}][{alpha}pre]"
            )
            filter_parts.append(f"[{alpha}pre]format=gray[{alpha}]")
            filter_parts.append(f"[{sped}][{alpha}]alphamerge[{rgba}]")
            filter_parts.append(
                f"[{cur}][{rgba}]overlay=enable='between(t,{b['start']},{b['end']})'[{out_label}]"
            )
        else:
            panned = f"flarepan{i}"
            pan_x = f"'((t-{b['start']})/{dur})*{FLARE_WIDTH}-{CANVAS_W}'"
            filter_parts.append(
                f"[{input_idx}:v]crop={CANVAS_W}:{CANVAS_H}:x={pan_x}:y=0[{panned}]"
            )
            filter_parts.append(
                f"[{cur}][{panned}]overlay=enable='between(t,{b['start']},{b['end']})'[{out_label}]"
            )
        cur = out_label
        input_idx += 1

    # Picture-in-picture beats: small bordered card in a corner (ebook cover,
    # course-catalog "video penjelasan" screen recording, etc), talking head
    # still fully visible — NOT a full-frame cutaway. See PIP_* constants.
    for i, b in enumerate(pips):
        src_w, src_h = get_source_dimensions(b["source"])
        card_w = PIP_WIDTH
        card_h = round(PIP_WIDTH * src_h / src_w)
        position = b.get("position", "top-right")
        px, py = PIP_POSITIONS.get(position, PIP_POSITIONS["top-right"])
        if py is None:  # bottom-anchored: compute from card height
            py = CANVAS_H - card_h - 2 * PIP_BORDER - 260
        scaled = f"pipscale{i}"
        out_label = f"pip{i}"
        filter_parts.append(
            f"[{input_idx}:v]scale={card_w}:{card_h},format=yuva420p,"
            f"pad={card_w + 2 * PIP_BORDER}:{card_h + 2 * PIP_BORDER}:{PIP_BORDER}:{PIP_BORDER}:color=white[{scaled}]"
        )
        filter_parts.append(
            f"[{cur}][{scaled}]overlay=x={px}:y={py}:enable='between(t,{b['start']},{b['end']})'[{out_label}]"
        )
        cur = out_label
        input_idx += 1
        label = b.get("label")
        if label:
            # Wrap to fit the CARD's own width, not the full canvas — an
            # earlier version centered the whole label string under the
            # card's x-center without checking its rendered width, so a
            # longer label ran straight off the right edge of frame while
            # narrow cards (needed to clear the subject's face — see
            # PIP_WIDTH's comment) don't have room for a wide one-liner.
            fontsize = 38
            max_line_w = card_w + 2 * PIP_BORDER + 40  # a little wider than the card is fine
            lines = wrap_text_to_width(label.upper(), _PIP_LABEL_FONT_PATH, fontsize, max_line_w)
            label_x = px + (card_w + 2 * PIP_BORDER) / 2
            label_top = py + card_h + 2 * PIP_BORDER + 16
            line_height = fontsize + 12
            for li, line in enumerate(lines):
                escaped = line.replace("'", "\\'").replace(":", "\\:")
                out_label2 = f"piplabel{i}_{li}"
                line_y = label_top + li * line_height
                filter_parts.append(
                    f"[{cur}]drawtext=fontfile='{_PIP_LABEL_FONT_PATH}':text='{escaped}':"
                    f"fontsize={fontsize}:fontcolor=white:borderw=4:bordercolor=black:"
                    f"x={label_x}-text_w/2:y={line_y}:"
                    f"enable='between(t,{b['start']},{b['end']})'[{out_label2}]"
                )
                cur = out_label2

    filter_parts.append(f"[{cur}]subtitles={ass_path}:fontsdir=fonts[vout]")

    audio_out = "0:a"
    if sfx_beats:
        sfx_input_start = input_idx
        sfx_labels = []
        for i, b in enumerate(sfx_beats):
            sfx_idx = sfx_input_start + i
            delay_ms = max(0, round(b["start"] * 1000))
            label = f"sfx{i}"
            filter_parts.append(f"[{sfx_idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
            sfx_labels.append(label)
        mix_inputs = "[0:a]" + "".join(f"[{lbl}]" for lbl in sfx_labels)
        n = 1 + len(sfx_labels)
        filter_parts.append(f"{mix_inputs}amix=inputs={n}:duration=first:dropout_transition=0[aout]")
        audio_out = "[aout]"

    filter_complex = ";".join(filter_parts)

    cmd = [
        resolve_ffmpeg(), "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", audio_out,
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "aac",
        "-shortest",  # looped slide-image inputs are infinite; stop at the main video's length
        args.out,
    ]
    print("[render] running ffmpeg...")
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"[render] wrote {args.out}")


if __name__ == "__main__":
    main()
