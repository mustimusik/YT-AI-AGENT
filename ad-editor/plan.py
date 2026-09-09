"""
plan.py — calls Claude to turn your aligned script + b-roll pool into an
Edit Decision List (EDL) JSON. This is the "AI suggests" step — the output
is a plain JSON file you are expected to read and tweak before rendering.

Usage:
    export ANTHROPIC_API_KEY=sk-...
    python plan.py --words words.json --broll broll_manifest.json --out edl.json

broll_manifest.json format (you write this once per project — short tags,
not essays):
[
  {"file": "broll/hands_closeup_1.mp4", "tags": "piano hands playing chords, warm lit"},
  {"file": "broll/crowd_event.mp4", "tags": "church crowd, social proof, energetic"}
]
"""
import argparse
import json
import sys
from pathlib import Path

import anthropic

from validate_edl import EDLValidationError, validate_edl

EDL_SCHEMA_EXAMPLE = {
    "video_meta": {"width": 1080, "height": 1920, "fps": 30},
    "captions": [
        {
            "start": 1.4, "end": 2.6,
            "words": [
                {"text": "CHORDNYA", "accent": None},
                {"text": "DULU", "accent": "gold"}
            ]
        }
    ],
    "beats": [
        {"type": "zoom_punch", "start": 9.7, "end": 14.6, "zoom_from": 1.0, "zoom_to": 1.15},
        {"type": "cutaway", "start": 6.0, "end": 8.3, "source": "broll/hands_closeup_1.mp4", "tint": "warm"},
        {"type": "slide", "start": 30.0, "end": 32.0, "text": "99", "subtext": "RIBU AJA", "style": "price_reveal"},
        {"type": "chord_label", "start": 20.0, "end": 20.8, "text": "Am"},
    ]
}


def build_prompt(style_bible: str, words: list, broll_manifest: list) -> str:
    return f"""You are an edit planner for short-form vertical ads (1080x1920).
Follow the STYLE BIBLE exactly — it was extracted from the creator's own
winning ads. Do not invent a different style.

STYLE BIBLE:
{style_bible}

You are given the ad's script as a list of words with exact start/end times
(seconds), already aligned to the voiceover audio. You are also given a pool
of available b-roll clips with short tags describing their content.

WORDS (JSON, in speaking order):
{json.dumps(words, ensure_ascii=False)}

AVAILABLE B-ROLL:
{json.dumps(broll_manifest, ensure_ascii=False)}

Produce an Edit Decision List (EDL) as a single JSON object with this exact
shape (see field meanings from this example — do not copy its content,
generate real content from the WORDS above):

{json.dumps(EDL_SCHEMA_EXAMPLE, indent=2)}

Rules:
- "captions": group WORDS into 2-4 word phrases covering the ENTIRE script
  from first word's start to last word's end, no gaps, no overlaps. Pick
  0-2 accent words per phrase per the style bible's color rules
  (accent: "gold" | "red" | None).
- "beats": place pattern-interrupt beats (cutaway / zoom_punch / slide /
  chord_label) so that no shot runs longer than ~5s uninterrupted, per the
  pacing rule. Vary the interrupt type — do not repeat the same beat type
  back-to-back. Only use "source" files that exist in AVAILABLE B-ROLL.
  Use "slide" beats for big numbers/offers/claims per the style bible,
  not regular captions.
- Times must stay within the script's total duration and be internally
  consistent (start < end, beats don't need to avoid overlapping each
  other across different types, e.g. a caption plays under a cutaway).
- Output ONLY the JSON object. No markdown fences, no commentary.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--words", required=True)
    ap.add_argument("--broll", required=True, help="broll_manifest.json")
    ap.add_argument("--style-bible", default="style_bible.md")
    ap.add_argument("--out", default="edl.json")
    ap.add_argument("--model", default="claude-sonnet-5")
    args = ap.parse_args()

    words = json.loads(Path(args.words).read_text(encoding="utf-8"))
    broll_manifest = json.loads(Path(args.broll).read_text(encoding="utf-8"))
    style_bible = Path(args.style_bible).read_text(encoding="utf-8")

    prompt = build_prompt(style_bible, words, broll_manifest)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    resp = client.messages.create(
        model=args.model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(block.text for block in resp.content if block.type == "text")

    # Be forgiving if the model wraps output in a code fence anyway.
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        edl = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[plan] ERROR: Claude's response wasn't valid JSON: {e}", file=sys.stderr)
        print(f"[plan] raw response:\n{raw_text}", file=sys.stderr)
        sys.exit(1)

    try:
        validate_edl(edl, broll_manifest)
    except EDLValidationError as e:
        # Still write the file — it's often easier to fix by hand than to
        # regenerate, and the whole point of the EDL being plain JSON is
        # that you can just open and edit it.
        Path(args.out).write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[plan] wrote {args.out}, but it has problems:", file=sys.stderr)
        print(str(e), file=sys.stderr)
        print(
            f"[plan] Fix these in {args.out} before running render.py "
            "(render.py will also re-validate and refuse to run otherwise).",
            file=sys.stderr,
        )
        sys.exit(1)

    Path(args.out).write_text(json.dumps(edl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[plan] wrote {args.out} — REVIEW THIS FILE before rendering.")


if __name__ == "__main__":
    main()
