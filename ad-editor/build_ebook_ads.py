#!/usr/bin/env python3
"""
build_ebook_ads.py — one-off orchestrator for the ebook ad batch (7 hook
variants sharing one Body+CTA). Cuts each hook + the shared body/cta straight
from the source recording using the REAL whisper word timestamps (no need to
re-run align.py's script-fuzzy-matching — we already have exact ASR timing
for every word we're keeping, which is strictly more accurate than aligning
to the written script for caption sync).

This plays the role of `plan.py` too (EDL-building), done here in code
instead of an Anthropic API call, per the request to use local reasoning
instead of a live API key.

Usage:
    python3 build_ebook_ads.py --hook 1          # build just hook 1 (for review)
    python3 build_ebook_ads.py --all             # build all 7
"""
import argparse
import json
import subprocess
from pathlib import Path

from align import align_script_to_whisper, tokenize

ROOT = Path(__file__).parent
SRC_VIDEO = ROOT / "ebook_ad" / "source.mp4"
RAW_WHISPER = ROOT / "ebook_ad" / "raw_whisper.json"
WORK = ROOT / "ebook_ad" / "work"
OUT_DIR = ROOT / "ebook_ad" / "output"

FPS = 30
CANVAS_W, CANVAS_H = 1080, 1920

# Talking-head crop: source is native 1080x1920 but framed with a lot of
# empty headspace above the subject. Crops to ~83% width/height (centered
# horizontally, biased down vertically to cut mostly from the top) then
# scales back up to canvas size — tighter framing matching the reference
# ads (face fills more of the frame, minimal blank space above the head).
CROP_FILTER = "crop=900:1600:90:280,scale=1080:1920"

# Real SFX from the team's own library (sfx_lib/), per their usage rules:
#   - video transition -> "flare" beat (camera-flare pan, see render.py)
#   - audio at that same cut -> rotate camera shutter / mouse click / camera flash
#   - highlighted (accented) words -> rotate bell / mouse click / angin ("hyut")
#   - any sentence containing "manis" -> sparkling.MP3
SFX_DIR = ROOT / "sfx_lib"
TRANSITION_SFX = [
    str(SFX_DIR / "camera shutter.MP3"),
    str(SFX_DIR / "mouse click 1.MP3"),
    str(SFX_DIR / "camera flash.MP3"),
]
# Real flare transition footage (team-provided, replaces the earlier
# synthetic pan-and-glow). Each is a ~6s black->bloom->black cycle meant to
# be sped up (render.py's "flare" beat handles this via setpts when a
# "source" is given) rather than played at native speed.
TRANSITIONS_DIR = ROOT / "transitions"
FLARE_SOURCES = [
    str(TRANSITIONS_DIR / "flare_1.mp4"),
    str(TRANSITIONS_DIR / "flare_2.mp4"),
]
FLARE_DURATION = 0.8  # compressed on-screen duration of the sped-up flare beat
HIGHLIGHT_SFX = [
    str(SFX_DIR / "bell.MP3"),
    str(SFX_DIR / "mouse click 2.MP3"),
    str(SFX_DIR / "angin.MP3"),  # "hyut" — the whoosh/wind sound
]
SPARKLE_SFX = str(SFX_DIR / "sparkling.MP3")

BROLL_DIR = ROOT / "broll"
VIDEO_PENJELASAN_BROLL = str(BROLL_DIR / "video penjelasan.mp4")
HANDS_CLOSEUP_BROLL = str(BROLL_DIR / "IMG_3363.MOV")  # Jeremy, pelayanan close-up
EBOOK_VISUAL = str(ROOT / "visual_buku" / "buat lagu.jpeg")

# (start, end) in the SOURCE video's timeline, hand-picked from the real
# transcript — see conversation notes for why each boundary was chosen
# (retake clusters skipped, self-asides excluded, final takes kept).
HOOK_RANGES = {
    1: (17.08, 21.68),
    2: (56.28, 58.96),
    3: (70.46, 80.18),
    4: (97.58, 108.86),
    5: (114.46, 119.76),
    6: (127.74, 137.14),
    7: (144.22, 149.92),
}
BODY_RANGE = (23.42, 34.00)
CTA_RANGE = (44.42, 50.04)

# What was ACTUALLY said in each kept segment, correctly spelled — NOT the
# original written script verbatim. Two hooks (2, 6) diverged enough from
# the written script during shooting that reusing the actual take's wording
# is more faithful than forcing the original line; the CTA's kept portion
# skips a fumbled sentence entirely (see conversation notes). This is the
# reference text fed to align_script_to_whisper for correct-spelling,
# real-timed captions — using raw Whisper text directly for captions was
# the v1 mistake here (e.g. "aransemen" mis-heard and mis-spelled).
HOOK_CLEAN_TEXT = {
    1: "Kau punya ide melodi atau lirik? Pengen banget buat lagu tapi bingung gimana caranya.",
    2: "Kau pemain band dan pengen bisa aransemen lagu sendiri.",
    3: "Kamu udah pernah buat lagu tapi ngerasa semuanya kedengeran mirip karena progresi chordnya gitu-gitu doang.",
    4: "Kau bisa main piano, tapi pengen upgrade skill untuk buat lagu sendiri.",
    5: "Kamu udah main piano bertahun-tahun tapi ngerasa cuma jago main lagu doang. Belum pernah bikin karya sendiri.",
    6: "Kau pernah nyoba iseng bikin lagu sendiri di piano, tapi gak pernah bisa develop jadi lagu yang full.",
    7: "Aku punya ide untuk buat lagu, tapi begitu duduk di depan piano gak tahu harus mulai dari mana.",
}
BODY_CLEAN_TEXT = (
    "Aku baru banget buat ebook cara buat dan aransemen lagu yang isinya lengkap banget. "
    "Kamu mau kan belajar secara step-by-step, mulai dari pahami struktur dan progresi lagu, "
    "sampai nanti kamu bisa buat dan arrange lagu kamu sendiri."
)
CTA_CLEAN_TEXT = (
    "Dan kamu bisa dapetin dengan harga 99 ribu aja, "
    "jadi buruan klik link di bawah buat dapetin ebooknya."
)

# Simple keyword-based accent rules, per style_bible.md's color rules.
# Matched case-insensitively against normalized (punctuation-stripped) words.
GOLD_KEYWORDS = {
    "ebook", "lengkap", "stepbystep", "step", "arrange", "aransemen",
    "struktur", "progresi", "sendiri", "video", "penjelasan",
}
RED_KEYWORDS = {"buruan", "klik", "aja"}


def run(cmd):
    print("+ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def ffprobe_duration(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def cut_clip(start, end, out_path):
    if out_path.exists():
        return
    run([
        "ffmpeg", "-y", "-ss", str(start), "-to", str(end), "-i", str(SRC_VIDEO),
        "-vf", CROP_FILTER,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(out_path),
    ])


# Internal dead-air trimming: a segment kept as one continuous range can
# still contain a real pause mid-sentence/mid-paragraph (a breath, a beat
# before the next sentence) that's way longer than natural speech rhythm
# calls for. Ads need to stay tight — any internal gap longer than
# MAX_INTERNAL_PAUSE gets trimmed down to KEEP_PAUSE instead of left as dead
# air on screen.
MAX_INTERNAL_PAUSE = 0.45
KEEP_PAUSE = 0.12


def plan_trimmed_ranges(words, seg_lo, seg_hi):
    """
    Returns (ranges, gap_starts) where `ranges` is a list of (start, end) in
    SOURCE video time to extract & concat for this segment (splicing out any
    internal pause longer than MAX_INTERNAL_PAUSE, leaving KEEP_PAUSE of
    natural breathing room instead), and `gap_starts` is the output-timeline
    position of each cut point (for flash/zoom beat placement, if desired).
    """
    ranges = []
    cur_start = seg_lo
    for i in range(len(words) - 1):
        gap = words[i + 1]["start"] - words[i]["end"]
        if gap > MAX_INTERNAL_PAUSE:
            cur_end = words[i]["end"] + KEEP_PAUSE
            ranges.append((cur_start, cur_end))
            cur_start = words[i + 1]["start"]
    ranges.append((cur_start, seg_hi))
    return ranges


def retime_for_trimmed_ranges(words, ranges, target_offset):
    """
    Retime `words` (absolute source-video timestamps) onto the OUTPUT
    timeline produced by concatenating `ranges` back-to-back starting at
    target_offset. Words are expected to fall within the union of `ranges`
    (words inside a trimmed-out gap don't exist — gaps are between words by
    construction).
    """
    # cumulative output-time at the start of each source range
    range_output_starts = []
    acc = target_offset
    for r_start, r_end in ranges:
        range_output_starts.append(acc)
        acc += r_end - r_start

    def to_output_time(t):
        for (r_start, r_end), out_start in zip(ranges, range_output_starts):
            if r_start - 0.01 <= t <= r_end + 0.01:
                return out_start + (t - r_start)
        # shouldn't happen if ranges were built from these words, but fall
        # back to clamping into the nearest range rather than crashing
        r_start, r_end = ranges[-1]
        return range_output_starts[-1] + max(0.0, min(t, r_end) - r_start)

    return [
        {"text": w["text"], "start": round(to_output_time(w["start"]), 3),
         "end": round(to_output_time(w["end"]), 3)}
        for w in words
    ]


def cut_clip_trimmed(ranges, out_path):
    """Extract each (start,end) range and concat them into one clip (internal pauses removed)."""
    if out_path.exists():
        return
    if len(ranges) == 1:
        cut_clip(ranges[0][0], ranges[0][1], out_path)
        return
    part_paths = []
    for i, (start, end) in enumerate(ranges):
        part_path = out_path.with_suffix(f".part{i}.mp4")
        cut_clip(start, end, part_path)
        part_paths.append(part_path)
    concat_copy(part_paths, out_path)


def concat_copy(paths, out_path):
    list_path = out_path.with_suffix(".txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p.resolve()}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-c", "copy", str(out_path)])


def normalize(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum())


def words_in_range(all_words, lo, hi):
    return [w for w in all_words if w["start"] >= lo - 0.02 and w["end"] <= hi + 0.02]


def aligned_words_for_segment(clean_text, all_whisper_words, lo, hi):
    """
    Correct-spelling, real-timed words for one segment: align the ACTUAL
    (hand-corrected) transcript text against the real Whisper words in this
    segment's time range, per align.py's hardened two-pass approach. This
    is what fixes captions showing raw ASR errors (e.g. "aran sama" instead
    of "aransemen") — v1 of this script used the raw Whisper words directly
    for captions, which was wrong for exactly this reason.
    """
    segment_whisper_words = words_in_range(all_whisper_words, lo, hi)
    return align_script_to_whisper(tokenize(clean_text), segment_whisper_words)


def retime(words, source_offset, target_offset):
    out = []
    for w in words:
        out.append({
            "text": w["text"].strip(),
            "start": round(w["start"] - source_offset + target_offset, 3),
            "end": round(w["end"] - source_offset + target_offset, 3),
        })
    return out


def accent_for(word_text: str):
    norm = normalize(word_text)
    if norm in RED_KEYWORDS:
        return "red"
    if norm in GOLD_KEYWORDS:
        return "gold"
    return None


def group_captions(words, phrase_size=3, final_end=None, no_bridge_ranges=None):
    """
    Group a flat word list into style-bible-compliant 2-4 word caption
    phrases. Each caption's `end` is normally stretched forward to the NEXT
    caption's `start` (or `final_end` for the last one) rather than the last
    word's own end timestamp — real speech has small inter-word gaps, and
    plan.py's own prompt requires continuous no-gap caption coverage (letting
    a caption's text disappear during a 0.2s natural pause just reads as
    flicker, not as intentional timing).

    `no_bridge_ranges`: gaps that fall inside one of these (start, end)
    windows are left as real gaps instead of bridged. This is for slide
    beats — render.py draws captions on top of EVERYTHING including slides,
    so a caption whose bridged span crosses a slide's window would float
    over the "99RB" price card, stepping on the one moment the style bible
    says should be caption-free (the number gets its own oversized
    standalone treatment specifically so nothing else is competing for
    attention on screen).
    """
    no_bridge_ranges = no_bridge_ranges or []

    def bridge_blocked(gap_start, gap_end):
        return any(gap_start < r_end and gap_end > r_start for r_start, r_end in no_bridge_ranges)

    # Chunk by phrase_size, but ALWAYS end a chunk right after a word ending
    # in sentence punctuation — a phrase must never straddle a sentence
    # boundary (style bible), even if that leaves a short 1-2 word phrase.
    chunks = []
    current = []
    for w in words:
        current.append(w)
        ends_sentence = w["text"].rstrip()[-1:] in ".?!"
        if ends_sentence or len(current) >= phrase_size:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    captions = []
    for i, chunk in enumerate(chunks):
        natural_end = chunk[-1]["end"]
        next_start = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else final_end
        if next_start is not None and not bridge_blocked(natural_end, next_start):
            end = max(next_start, natural_end)
        else:
            end = natural_end
        captions.append({
            "start": chunk[0]["start"],
            "end": end,
            "words": [
                {"text": w["text"].upper(), "accent": accent_for(w["text"])}
                for w in chunk
            ],
        })
    return captions


def find_word_span(words, needle_norms):
    """Find the (start,end) covering a run of words matching needle_norms in order."""
    n = len(needle_norms)
    for i in range(len(words) - n + 1):
        if all(normalize(words[i + k]["text"]) == needle_norms[k] for k in range(n)):
            return words[i]["start"], words[i + n - 1]["end"]
    return None


def build_captions_around_slides(caption_words, slide_beats, total_duration):
    """
    Chunk caption_words into phrases, but split into independent segments at
    each slide beat's boundaries FIRST. Chunking the flat word list in one
    pass and only blocking cross-segment *bridging* isn't enough: with the
    slide's words already removed from caption_words, the words immediately
    before and after the slide become adjacent in the list, so a single
    phrase_size=3 chunk can end up spanning "harga" (before the slide) +
    "aja, jadi" (after it) — one caption whose OWN start/end already covers
    the entire slide window, floating over the price card the whole time it
    is up. Splitting into segments up front means no chunk can ever contain
    words from both sides of a slide to begin with.
    """
    slide_ranges = sorted((b["start"], b["end"]) for b in slide_beats)

    segments = []  # each: (words_in_segment, segment_end_bound_or_None)
    cursor = 0.0
    remaining = list(caption_words)
    for s_start, s_end in slide_ranges:
        before = [w for w in remaining if w["end"] <= s_start]
        remaining = [w for w in remaining if w["start"] >= s_end]
        if before:
            segments.append((before, s_start))
        cursor = s_end
    if remaining:
        segments.append((remaining, total_duration))

    captions = []
    for words, seg_end in segments:
        captions.extend(group_captions(words, final_end=seg_end))
    return captions


def snap_in_ease_out(cut_time, segment_end, zoom_peak=1.15, snap_dur=0.08, ease_dur=2.5):
    """
    The two beats that make up one "snap-zoom-in-then-release" moment at a
    cut, per style_bible.md's Zoom section: near-instant punch in right at
    the cut (not a glide), then ease back to 1.0x over the next couple
    seconds. Returns a list of 1-2 zoom_punch beat dicts (clamped to not run
    past segment_end, in case the segment is shorter than ease_dur).
    """
    beats = [{"type": "zoom_punch", "start": cut_time, "end": min(cut_time + snap_dur, segment_end),
              "zoom_from": 1.0, "zoom_to": zoom_peak}]
    ease_end = min(cut_time + snap_dur + ease_dur, segment_end)
    if ease_end > cut_time + snap_dur:
        beats.append({"type": "zoom_punch", "start": cut_time + snap_dur, "end": ease_end,
                      "zoom_from": zoom_peak, "zoom_to": 1.0})
    return beats


def build_edl_for_hook(hook_words, body_words, cta_words, total_duration):
    """
    Assemble the full EDL for one hook+body+cta video. This is the part that
    would normally be plan.py's Claude API call — done directly here instead,
    following style_bible.md by hand:
      - captions: phrase-grouped, accented per keyword rules, never spanning
        a sentence boundary
      - the price ("99 RIBU") gets pulled OUT of the caption stream and given
        its own slide beat (style bible: numbers/offers get oversized
        standalone treatment, not a caption over the face)
      - flash beats mark the hook->body and body->cta cuts (pattern interrupt,
        no b-roll available so cutaways aren't an option here)
      - zoom_punch: snap-in-then-release at each cut (style bible), not a
        slow continuous push-in — see snap_in_ease_out()
    """
    all_words = hook_words + body_words + cta_words
    hook_end = hook_words[-1]["end"] if hook_words else 0
    body_end = body_words[-1]["end"] if body_words else hook_end

    # Pull the price phrase out of CTA words into its own slide beat instead
    # of a caption.
    price_span = find_word_span(cta_words, ["99", "ribu"])
    caption_words = list(all_words)
    slide_beats = []
    if price_span:
        p_start, p_end = price_span
        caption_words = [
            w for w in caption_words if not (w["start"] >= p_start - 0.01 and w["end"] <= p_end + 0.01)
        ]
        slide_beats.append({
            "type": "slide", "start": p_start, "end": p_end + 1.0,
            "text": "99RB", "subtext": "AJA", "style": "price_reveal",
        })

    captions = build_captions_around_slides(caption_words, slide_beats, total_duration)

    beats = list(slide_beats)

    # Ebook cover: picture-in-picture card (per reference ads — a bordered
    # inset in the corner with a caption label underneath, talking head
    # still fully visible), NOT a full-frame cutaway. Shown at the moment
    # "ebook" is said.
    ebook_span = find_word_span(body_words, ["ebook"])
    if ebook_span:
        e_start, e_end = ebook_span
        beats.append({
            "type": "pip", "start": e_start, "end": e_end + 1.5,
            "source": EBOOK_VISUAL, "position": "top-right",
            "label": "DAPETIN EBOOK INI",
        })
    # Hands-closeup covers the "belajar step by step... arrange lagu
    # sendiri" technique explanation (the style bible's broll_hands use
    # case: b-roll during "explaining technique") — this one IS a full-frame
    # cutaway, per the reference mapping rules (hands b-roll replaces the
    # shot, unlike the ebook/course-catalog cards which stay inset).
    technique_start_span = find_word_span(body_words, ["belajar"])
    if technique_start_span and body_words:
        t_start = technique_start_span[0]
        beats.append({
            "type": "cutaway", "start": t_start, "end": body_end,
            "source": HANDS_CLOSEUP_BROLL,
        })
    # Flare (video) + rotating transition SFX (audio) at the two hard cuts
    # (hook->body, body->cta) — per the team's usage rules: video transition
    # = camera flare, audio side rotates between camera shutter / mouse
    # click / camera flash so it doesn't feel identical every time. Zoom
    # starts riding in at the SAME instant as the flare (both mark the cut).
    transition_i = 0
    half = FLARE_DURATION / 2
    if hook_words and body_words:
        sfx = TRANSITION_SFX[transition_i % len(TRANSITION_SFX)]
        flare_src = FLARE_SOURCES[transition_i % len(FLARE_SOURCES)]
        transition_i += 1
        beats.append({
            "type": "flare", "start": hook_end - half, "end": hook_end + half,
            "source": flare_src, "sfx": sfx,
        })
        beats += snap_in_ease_out(hook_end, body_end if body_words else total_duration)
    if body_words and cta_words:
        cta_start = cta_words[0]["start"]
        sfx = TRANSITION_SFX[transition_i % len(TRANSITION_SFX)]
        flare_src = FLARE_SOURCES[transition_i % len(FLARE_SOURCES)]
        transition_i += 1
        beats.append({
            "type": "flare", "start": cta_start - half, "end": cta_start + half,
            "source": flare_src, "sfx": sfx,
        })
        beats += snap_in_ease_out(cta_start, total_duration)
    # The very first segment (hook) opens on a cut into the ad itself — snap
    # it in at t=0 too rather than starting flat, so the hook doesn't read
    # as the one shot with no punch at all.
    if hook_words:
        beats += snap_in_ease_out(0, hook_end)

    # Highlight SFX on every accented (gold/red) word — rotate bell / mouse
    # click / angin so repeated highlights in one ad don't sound identical.
    # "manis" always gets the dedicated sparkle SFX instead (team rule),
    # overriding the rotation for that word specifically.
    highlight_i = 0
    for w in caption_words:
        norm = normalize(w["text"])
        if norm == "manis":
            beats.append({"type": "sfx", "start": w["start"], "end": w["start"] + 1.0, "sfx": SPARKLE_SFX})
        elif accent_for(w["text"]):
            sfx = HIGHLIGHT_SFX[highlight_i % len(HIGHLIGHT_SFX)]
            highlight_i += 1
            beats.append({"type": "sfx", "start": w["start"], "end": w["start"] + 0.4, "sfx": sfx})

    return {
        "video_meta": {"width": CANVAS_W, "height": CANVAS_H, "fps": FPS},
        "captions": captions,
        "beats": beats,
    }


def build_one(hook_num: int):
    WORK.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_words = json.loads(RAW_WHISPER.read_text(encoding="utf-8"))

    hook_lo, hook_hi = HOOK_RANGES[hook_num]
    body_lo, body_hi = BODY_RANGE
    cta_lo, cta_hi = CTA_RANGE

    # Align FIRST (need real word gaps to know where the internal dead air
    # is), then cut with those pauses spliced out, then retime words onto
    # the now-shorter timeline.
    hook_aligned = aligned_words_for_segment(HOOK_CLEAN_TEXT[hook_num], all_words, hook_lo, hook_hi)
    body_aligned = aligned_words_for_segment(BODY_CLEAN_TEXT, all_words, body_lo, body_hi)
    cta_aligned = aligned_words_for_segment(CTA_CLEAN_TEXT, all_words, cta_lo, cta_hi)

    hook_ranges = plan_trimmed_ranges(hook_aligned, hook_lo, hook_hi)
    body_ranges = plan_trimmed_ranges(body_aligned, body_lo, body_hi)
    cta_ranges = plan_trimmed_ranges(cta_aligned, cta_lo, cta_hi)

    hook_clip = WORK / f"hook{hook_num}_raw.mp4"
    body_clip = WORK / "body_raw.mp4"
    cta_clip = WORK / "cta_raw.mp4"
    cut_clip_trimmed(hook_ranges, hook_clip)
    cut_clip_trimmed(body_ranges, body_clip)
    cut_clip_trimmed(cta_ranges, cta_clip)

    combined = WORK / f"ad{hook_num}_combined.mp4"
    concat_copy([hook_clip, body_clip, cta_clip], combined)
    total_duration = ffprobe_duration(combined)

    hook_dur = sum(e - s for s, e in hook_ranges)
    body_dur = sum(e - s for s, e in body_ranges)

    hook_words = retime_for_trimmed_ranges(hook_aligned, hook_ranges, 0)
    body_words = retime_for_trimmed_ranges(body_aligned, body_ranges, hook_dur)
    cta_words = retime_for_trimmed_ranges(cta_aligned, cta_ranges, hook_dur + body_dur)

    edl = build_edl_for_hook(hook_words, body_words, cta_words, total_duration)
    edl_path = WORK / f"edl_hook{hook_num}.json"
    edl_path.write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] wrote {edl_path}")

    out_path = OUT_DIR / f"ebook_ad_hook{hook_num}.mp4"
    run([
        "python3", str(ROOT / "render.py"),
        "--video", str(combined),
        "--edl", str(edl_path),
        "--out", str(out_path),
    ])
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hook", type=int, help="build just this hook number (1-7)")
    ap.add_argument("--all", action="store_true", help="build all 7 hooks")
    args = ap.parse_args()

    if args.all:
        for n in sorted(HOOK_RANGES):
            build_one(n)
    elif args.hook:
        build_one(args.hook)
    else:
        raise SystemExit("Pass --hook N or --all")


if __name__ == "__main__":
    main()
