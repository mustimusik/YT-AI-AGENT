"""
align.py — forced alignment of a KNOWN script to a talking-head video's audio.

Why not just transcribe? Free ASR text is noisy (misheard words, no punctuation
you intended). Since you already write a script before recording, we instead:
  1. Run local Whisper on the audio to get rough word timestamps + rough text.
  2. Align your real script tokens against Whisper's tokens (sequence matching).
  3. Keep YOUR script's wording, but inherit Whisper's timing per word.

This gives accurate caption timing without depending on ASR wording accuracy.

Usage:
    python align.py --video talking_head.mp4 --script script.txt --out words.json

Requires: faster-whisper (downloads a model the first time you run it with
internet access — after that it runs fully offline).
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel
from rapidfuzz import fuzz

from ffmpeg_util import resolve_ffmpeg


def extract_audio(video_path: str, wav_path: str):
    cmd = [
        resolve_ffmpeg(), "-y", "-i", video_path,
        "-ac", "1", "-ar", "16000", "-vn", wav_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def tokenize(text: str):
    # Keep it simple: lowercase word tokens, strip punctuation for matching,
    # but remember the ORIGINAL surface form to output in captions.
    raw_words = re.findall(r"\S+", text)
    return raw_words


def normalize(word: str) -> str:
    return re.sub(r"[^\w]", "", word).lower()


def whisper_words(video_path: str, model_size: str = "small"):
    with tempfile.TemporaryDirectory() as td:
        wav_path = str(Path(td) / "audio.wav")
        extract_audio(video_path, wav_path)
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(wav_path, word_timestamps=True, language="id")
        words = []
        for seg in segments:
            for w in seg.words:
                words.append({"text": w.word.strip(), "start": w.start, "end": w.end})
        return words


def align_script_to_whisper(script_words, wsp_words, min_score: int = 60):
    """
    Two-pass alignment, designed around real (retake-heavy) recordings.

    An earlier version did a single greedy pass: for each script word, fuzzy-
    match against a lookahead window of Whisper words, consuming as it went.
    That has a fundamental problem with retakes. A speaker who flubs a line
    usually re-records the WHOLE sentence, so an abandoned attempt's words
    sit in the Whisper transcript between the current pointer and the take
    that actually matches. Two failure modes fight each other:
      - a SMALL window can't see past a long abandoned attempt, so it grabs
        the nearest plausible-but-wrong word from the failed take;
      - a LARGE window can see far enough to skip retakes, but that also
        means it can accidentally match a script word to a coincidentally
        similar-looking Whisper word much further away (e.g. script "seat"
        scoring higher against a stray mis-transcribed "satu" five words
        later than against the real, but only 57%-similar, "sit" right in
        front of it) — and once that wrong jump happens, every subsequent
        word is aligned from the wrong position, cascading into a mostly-
        garbage alignment. This was verified empirically on a real retake-
        heavy recording, not theoretical.

    The fix: don't rely on one global window size at all.

    Pass 1 — global anchors via exact-match sequence alignment
    (`difflib.SequenceMatcher` over normalized tokens). This finds the
    longest common subsequence of EXACTLY-matching normalized words between
    script and Whisper output, in order. Crucially this is a *global*
    optimization, not a local greedy choice, so it can't be fooled by one
    coincidentally-similar word the way local fuzzy search can — a stray
    "satu" that merely resembles "seat" will never exactly-equal it, so it's
    never a candidate anchor. Anchors are only ever added in increasing
    (script_index, whisper_index) order, so they can never each other, and
    they naturally jump over abandoned retake clusters (whose words simply
    don't appear in the matching subsequence, since script only has the
    final wording once).

    Pass 2 — fill the gaps between anchors with fuzzy matching, but with the
    search STRICTLY BOUNDED to the Whisper index range between the
    surrounding anchors. This is what makes the fuzzy fallback safe here in
    a way the old global-window version wasn't: it is now structurally
    impossible for a gap-fill match to jump past a real anchor, because the
    search range ends there. A word with no good-enough match in its bounded
    gap is interpolated (placed right after the previous output word) rather
    than guessed at.
    """
    n_script = len(script_words)
    n_wsp = len(wsp_words)
    script_norm = [normalize(w) for w in script_words]
    wsp_norm = [normalize(w["text"]) for w in wsp_words]

    matcher = SequenceMatcher(None, script_norm, wsp_norm, autojunk=False)
    # (script_idx, whisper_idx) pairs for words that EXACTLY match (post-
    # normalization), in increasing order on both sides.
    anchors = []
    for a, b, size in matcher.get_matching_blocks():
        for k in range(size):
            if script_norm[a + k]:  # skip blanks (e.g. punctuation-only tokens)
                anchors.append((a + k, b + k))

    aligned = [None] * n_script
    low_confidence_count = 0
    last_output_end = 0.0

    def place(idx, start, end, is_anchor):
        nonlocal low_confidence_count, last_output_end
        start = max(start, last_output_end)
        end = max(end, start)
        aligned[idx] = {"text": script_words[idx], "start": round(start, 3), "end": round(end, 3)}
        last_output_end = end
        if not is_anchor:
            low_confidence_count += 1

    prev_script_i, prev_wsp_j = -1, -1
    # process the anchor chain, filling the gap before each anchor, then the anchor itself
    for script_i, wsp_j in anchors + [(n_script, n_wsp)]:  # sentinel closes the final gap
        gap_lo = prev_wsp_j + 1
        gap_hi = wsp_j  # exclusive
        for si in range(prev_script_i + 1, script_i):
            sw_norm = script_norm[si]
            best_j, best_score = None, 0
            if sw_norm:
                for j in range(gap_lo, gap_hi):
                    score = fuzz.ratio(sw_norm, wsp_norm[j])
                    if score > best_score:
                        best_score, best_j = score, j
            if best_j is not None and best_score >= min_score:
                place(si, wsp_words[best_j]["start"], wsp_words[best_j]["end"], is_anchor=False)
                gap_lo = best_j + 1  # keep gap-fill monotonic too
            else:
                place(si, last_output_end, last_output_end + 0.25, is_anchor=False)

        if script_i < n_script:  # real anchor, not the sentinel
            place(script_i, wsp_words[wsp_j]["start"], wsp_words[wsp_j]["end"], is_anchor=True)

        prev_script_i, prev_wsp_j = script_i, wsp_j

    if low_confidence_count:
        print(
            f"[align] WARNING: {low_confidence_count}/{n_script} words had no "
            "confident exact/fuzzy match and were interpolated — review "
            "words.json for caption timing around those, especially near "
            "retakes, filler words, or foreign-language terms Whisper mishears.",
            file=sys.stderr,
        )

    return [w for w in aligned if w is not None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--script", required=True, help="Path to a .txt file with your VO script")
    ap.add_argument("--out", default="words.json")
    ap.add_argument("--model-size", default="medium",
                     help="tiny/base/small/medium/large-v3 (bigger = more accurate, slower). "
                          "medium+ strongly recommended for Indonesian with English loanwords "
                          "(workshop/chord/etc) — small mishears too many of them for alignment "
                          "to have anything to match against.")
    ap.add_argument("--min-score", type=int, default=60,
                     help="fuzzy match threshold (0-100) for filling gaps between exact-match anchors")
    args = ap.parse_args()

    script_text = Path(args.script).read_text(encoding="utf-8")
    script_words = tokenize(script_text)

    print(f"[align] transcribing audio with Whisper ({args.model_size})...", file=sys.stderr)
    wsp_words = whisper_words(args.video, args.model_size)
    print(f"[align] whisper found {len(wsp_words)} words, script has {len(script_words)}", file=sys.stderr)

    aligned = align_script_to_whisper(
        script_words, wsp_words, min_score=args.min_score,
    )

    Path(args.out).write_text(json.dumps(aligned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[align] wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
