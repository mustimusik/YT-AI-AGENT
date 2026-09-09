#!/usr/bin/env python3
"""
Transkripsi audio/video -> JSON word-level timestamp (Bahasa Indonesia),
pakai faster-whisper (CTranslate2, jalan di CPU, ga butuh GPU).

Output JSON-nya kompatibel dengan transcribe_ts.py di pipeline
(davehenokhliong/yt-video-editing-pipeline): { "segments": [ {start, end,
text, words: [{word, start, end, probability}] } ] }.

Usage:
    python transcribe.py input.mp4 transcript.json
    python transcribe.py input.mp4 transcript.json --model small --lang id

Model: tiny / base / small / medium / large-v3 / large-v3-turbo (default small).
Makin gede makin akurat tapi makin lambat. Model auto-download sekali, di-cache.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def extract_wav(src, wav_path):
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-i", str(src), "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", str(wav_path)],
        check=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--model", default="small")
    ap.add_argument("--lang", default="id")
    ap.add_argument("--compute-type", default="int8",
                    help="int8 (cepat, CPU) / int8_float16 / float32")
    args = ap.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper belum keinstall. Jalanin:\n"
                 "  py -3 -m pip install faster-whisper")

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"File ga ketemu: {src}")

    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "audio.wav"
        print("Extract audio 16kHz mono...")
        extract_wav(src, wav)

        print(f"Load model ({args.model}, {args.compute_type})...")
        model = WhisperModel(args.model, device="cpu",
                             compute_type=args.compute_type)

        print("Transcribing (word timestamps)...")
        segments, info = model.transcribe(
            str(wav), language=args.lang, task="transcribe",
            word_timestamps=True, vad_filter=True,
        )

        out_segments = []
        full_text = []
        for seg in segments:
            words = [
                {"word": w.word, "start": round(w.start, 3),
                 "end": round(w.end, 3), "probability": round(w.probability, 3)}
                for w in (seg.words or [])
            ]
            out_segments.append({
                "id": seg.id, "start": round(seg.start, 3),
                "end": round(seg.end, 3), "text": seg.text, "words": words,
            })
            full_text.append(seg.text.strip())
            print(f"[{seg.start:7.2f} -> {seg.end:7.2f}] {seg.text.strip()}")

    result = {
        "language": info.language,
        "duration": round(info.duration, 3),
        "text": " ".join(full_text),
        "segments": out_segments,
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {args.output}  ({len(out_segments)} segmen)")


if __name__ == "__main__":
    main()


