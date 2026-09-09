"""
validate_edl.py — structural + semantic validation for an EDL before it's
handed to render.py.

Why this exists: plan.py's output comes from an LLM. It usually follows the
schema, but "usually" isn't good enough right before an ffmpeg run that can
take a while and fail with a confusing filtergraph error deep inside ffmpeg's
own stderr. This catches the common failure modes early with a message that
actually says what's wrong and where.

Checked, matching the EDL contract described in plan.py / README.md:
- top-level shape (video_meta / captions / beats present with right types)
- caption entries: start < end, each word has "text" + valid "accent"
- captions cover the full script from first to last word with no gaps or
  overlaps (this is a rule plan.py's own prompt asks the LLM to follow —
  worth checking it actually did)
- beat entries: known "type", required fields present for that type,
  start < end
- cutaway/chord_label beats' time ranges are sane; cutaway "source" exists
  in the b-roll manifest (if a manifest was passed in)
- flash/zoom_punch beats have consistent from/to fields where applicable

This does NOT try to re-implement full JSON Schema — it's a small, readable,
dependency-free set of checks tailored to this one EDL shape. If the schema
grows a lot more complex, swap this for the `jsonschema` package instead.
"""
from pathlib import Path

VALID_ACCENTS = {None, "gold", "red"}
VALID_BEAT_TYPES = {"zoom_punch", "cutaway", "slide", "chord_label", "flash", "flare", "sfx"}

REQUIRED_BEAT_FIELDS = {
    "zoom_punch": ["start", "end"],
    "cutaway": ["start", "end", "source"],
    "slide": ["start", "end", "text"],
    "chord_label": ["start", "end", "text"],
    "flash": ["start", "end"],
    "flare": ["start", "end"],
    "sfx": ["start", "end", "sfx"],  # audio-only cue, no visual — e.g. a highlight "ding" on an accented word
}


class EDLValidationError(Exception):
    """Raised with all collected problems, not just the first one found."""


def _fmt_errors(errors: list) -> str:
    return "EDL failed validation (" + str(len(errors)) + " problem(s)):\n" + "\n".join(
        f"  - {e}" for e in errors
    )


def validate_edl(edl: dict, broll_manifest: list | None = None) -> None:
    """Raises EDLValidationError with a full list of problems, or returns None."""
    errors = []

    if not isinstance(edl, dict):
        raise EDLValidationError(_fmt_errors(["EDL root must be a JSON object"]))

    # Gaps in caption coverage are fine when a "slide" beat owns that window.
    # render.py draws captions on top of slides, so deliberately leaving a
    # caption-free gap under a slide (the price/offer card) is the CORRECT
    # shape, not a mistake — see build_ebook_ads.py's group_captions for the
    # producer side of this same rule.
    slide_ranges = [
        (b["start"], b["end"]) for b in edl.get("beats", [])
        if isinstance(b, dict) and b.get("type") == "slide"
        and isinstance(b.get("start"), (int, float)) and isinstance(b.get("end"), (int, float))
    ]

    def gap_covered_by_slide(gap_start, gap_end):
        return any(gap_start < s_end and gap_end > s_start for s_start, s_end in slide_ranges)

    # --- video_meta ---
    meta = edl.get("video_meta")
    if not isinstance(meta, dict):
        errors.append("video_meta is missing or not an object")
    else:
        for key in ("width", "height", "fps"):
            if key not in meta:
                errors.append(f"video_meta.{key} is missing")

    # --- captions ---
    captions = edl.get("captions")
    if not isinstance(captions, list):
        errors.append("captions is missing or not a list")
        captions = []

    prev_end = None
    for i, cap in enumerate(captions):
        label = f"captions[{i}]"
        if not isinstance(cap, dict):
            errors.append(f"{label} is not an object")
            continue
        start, end = cap.get("start"), cap.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"{label}: start/end must be numbers")
        elif start >= end:
            errors.append(f"{label}: start ({start}) must be < end ({end})")
        else:
            if prev_end is not None:
                if start > prev_end + 0.01 and not gap_covered_by_slide(prev_end, start):
                    errors.append(
                        f"{label}: gap in captions between {prev_end} and {start} "
                        "(plan.py's prompt requires continuous coverage, no gaps — "
                        "unless a \"slide\" beat covers this window, which it doesn't here)"
                    )
                elif start < prev_end - 0.01:
                    errors.append(
                        f"{label}: overlaps previous caption "
                        f"(starts at {start}, previous ended at {prev_end})"
                    )
            prev_end = end

        words = cap.get("words")
        if not isinstance(words, list) or not words:
            errors.append(f"{label}: words must be a non-empty list")
        else:
            for j, w in enumerate(words):
                if not isinstance(w, dict) or "text" not in w:
                    errors.append(f"{label}.words[{j}]: missing \"text\"")
                    continue
                accent = w.get("accent")
                if accent not in VALID_ACCENTS:
                    errors.append(
                        f"{label}.words[{j}] ({w.get('text')!r}): "
                        f"accent must be one of {sorted(str(a) for a in VALID_ACCENTS)}, got {accent!r}"
                    )

    # --- beats ---
    beats = edl.get("beats")
    if not isinstance(beats, list):
        errors.append("beats is missing or not a list")
        beats = []

    broll_files = None
    if broll_manifest is not None:
        broll_files = {entry.get("file") for entry in broll_manifest if isinstance(entry, dict)}

    for i, beat in enumerate(beats):
        label = f"beats[{i}]"
        if not isinstance(beat, dict):
            errors.append(f"{label} is not an object")
            continue

        btype = beat.get("type")
        if btype not in VALID_BEAT_TYPES:
            errors.append(f"{label}: unknown beat type {btype!r} (valid: {sorted(VALID_BEAT_TYPES)})")
            continue

        for field in REQUIRED_BEAT_FIELDS[btype]:
            if field not in beat:
                errors.append(f"{label} (type={btype}): missing required field {field!r}")

        start, end = beat.get("start"), beat.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            if start >= end:
                errors.append(f"{label} (type={btype}): start ({start}) must be < end ({end})")
        else:
            errors.append(f"{label} (type={btype}): start/end must be numbers")

        if btype == "cutaway":
            source = beat.get("source")
            if broll_files is not None and source not in broll_files:
                errors.append(
                    f"{label}: source {source!r} is not in the b-roll manifest "
                    f"(available: {sorted(f for f in broll_files if f)})"
                )
            tint = beat.get("tint")
            if tint is not None and tint != "warm":
                errors.append(
                    f"{label}: tint {tint!r} is not implemented in render.py "
                    "(only \"warm\" or omitted) — it would be silently ignored at render time"
                )

        if btype == "zoom_punch":
            zf, zt = beat.get("zoom_from", 1.0), beat.get("zoom_to", 1.15)
            if not (isinstance(zf, (int, float)) and isinstance(zt, (int, float))):
                errors.append(f"{label}: zoom_from/zoom_to must be numbers")
            # Note: zoom_from > zoom_to (i.e. zooming back OUT) is valid — the
            # style bible's snap-in-then-release pattern is exactly two
            # zoom_punch beats where the second one eases from a peak back
            # down to 1.0. A continuous push-in-only segment (zoom_from <
            # zoom_to) is also valid. Neither direction alone is wrong; what
            # would actually be wrong (a single beat oscillating pointlessly)
            # isn't something this shape of check can detect anyway.

    if errors:
        raise EDLValidationError(_fmt_errors(errors))


def validate_edl_file(edl_path: str, broll_manifest_path: str | None = None) -> dict:
    """Convenience wrapper: load + validate from disk, return the parsed EDL on success."""
    import json

    edl = json.loads(Path(edl_path).read_text(encoding="utf-8"))
    broll_manifest = None
    if broll_manifest_path:
        broll_manifest = json.loads(Path(broll_manifest_path).read_text(encoding="utf-8"))
    validate_edl(edl, broll_manifest)
    return edl
