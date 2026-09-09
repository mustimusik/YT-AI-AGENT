#!/usr/bin/env python3
"""
Cut2 "pintar" — pakai transkrip word-level + deteksi hening buat motong:

  1. JEDA / hesitation ("eee", napas, mikir) di antara kata:
       - gap <= --keep-gap        -> biarin (ritme natural)
       - --keep-gap < gap <= --demo-gap  -> POTONG keras (ini biasanya "eee"/napas),
         sisain --pad di tiap sisi
       - gap > --demo-gap         -> ini kemungkinan demo piano: potong CUMA
         bagian yang hening, footage main piano dibiarin utuh
  2. FILLER word yang berdiri sendiri ("eee", "emm", "mm", "anu", "eh") -> buang.
  3. RETAKE / kalimat kembar (mirip >= --retake-sim sama tetangganya) -> buang
     yang lebih pendek/awal, keep yang paling lengkap. (--no-drop-retakes buat
     cuma laporin, ga motong.)
  4. INTERAKSI PENONTON / QNA -> segmen yang match pola di interaction_patterns.txt
     (mis. "siapa di sini yang", "ada pertanyaan", "coba tanya") dibuang. Ambil
     sesi ngajarnya aja.

Usage:
    python cutplan.py src.mp4 transcript.json -o out.mp4
    python cutplan.py src.mp4 transcript.json --json-only
    python cutplan.py src.mp4 transcript.json --demo-gap 3.0 --keep-gap 0.45 --pad 0.15

Butuh transcript.json dari transcribe.py.
"""
import argparse
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

# token hesitation murni (sengaja SEMPIT — "nah"/"ya"/"oke" itu gaya ngomong,
# bukan filler, jadi ga dimasukin)
FILLERS = {"eee", "ee", "e", "emm", "em", "eem", "mm", "mmm", "hmm", "hm",
           "eh", "ehm", "anu", "hmmm", "aa", "aaa"}

DEFAULT_INTERACTION_PATTERNS = [
    r"siapa (di sini|disini|yang di sini)",
    r"ada (yang|nggak yang|ga yang) (bisa|nggak bisa|ga bisa)",
    r"(ada|any) pertanyaan",
    r"pertanyaan(nya)? (dari|tadi|selanjutnya)",
    r"(coba|yang mau|silakan) (tanya|nanya|bertanya)",
    r"(kita|kita masuk ke) (sesi|bagian) (tanya jawab|qna|q&a|pertanyaan)",
    r"tulis di (kolom )?koment",
    r"koment(ar)? di bawah",
    r"like dan subscribe",
    r"jangan lupa (like|subscribe|share)",
    r"(ketik|tulis) \"?(bisa|paham|ngerti)\"? di",
    r"acungkan tangan",
    r"raise your hand",
]


def run(cmd):
    print("+ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def detect_silences(src, noise, min_silence):
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
         "-af", f"silencedetect=noise={noise}:d={min_silence}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", proc.stderr)]
    out = []
    for i, s in enumerate(starts):
        out.append((max(0.0, s), ends[i] if i < len(ends) else None))
    return out


def silence_overlap(t0, t1, silences, dur):
    span = max(1e-6, t1 - t0)
    ov = 0.0
    for s, e in silences:
        e = dur if e is None else e
        ov += max(0.0, min(t1, e) - max(t0, s))
    return ov / span


def load_words(transcript):
    words = []
    for seg in transcript["segments"]:
        for w in seg.get("words", []):
            tok = w["word"].strip()
            if tok:
                words.append({"w": tok, "start": w["start"], "end": w["end"],
                              "norm": re.sub(r"[^\w]", "", tok.lower())})
    return words


def load_interaction_patterns(path):
    pats = list(DEFAULT_INTERACTION_PATTERNS)
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                pats.append(line)
    return [re.compile(x, re.IGNORECASE) for x in pats]


def find_retake_pairs(transcript, thresh):
    segs = [s for s in transcript["segments"] if s["text"].strip()]
    pairs = []
    for a, b in zip(segs, segs[1:]):
        r = SequenceMatcher(None, a["text"].lower(), b["text"].lower()).ratio()
        if r >= thresh:
            pairs.append((a, b, round(r, 2)))
    return pairs


def subtract(segments, kills):
    """segments, kills: list of [s,e]. return segments minus union(kills)."""
    out = []
    for s, e in segments:
        pieces = [(s, e)]
        for ks, ke in kills:
            nxt = []
            for ps, pe in pieces:
                if ke <= ps or ks >= pe:
                    nxt.append((ps, pe))
                    continue
                if ks > ps:
                    nxt.append((ps, min(ks, pe)))
                if ke < pe:
                    nxt.append((max(ke, ps), pe))
            pieces = nxt
        out.extend(pieces)
    return out


def build_segments(words, silences, dur, keep_gap, demo_gap, pad, min_clip,
                   merge_gap, drop_fillers):
    if not words:
        return [], []

    # --- 1. isolated filler tokens -> kill list
    filler_kills = []
    dropped = []
    for i, w in enumerate(words):
        if drop_fillers and w["norm"] in FILLERS:
            prev_gap = w["start"] - words[i-1]["end"] if i > 0 else 99
            next_gap = words[i+1]["start"] - w["end"] if i+1 < len(words) else 99
            if prev_gap > 0.12 or next_gap > 0.12:
                filler_kills.append([w["start"] - 0.05, w["end"] + 0.05])
                dropped.append(w)

    live = [w for w in words if [w["start"] - 0.05, w["end"] + 0.05] not in filler_kills]

    # --- 2. bikin span bicara, putus di gap sesuai aturan tiga-tingkat
    spans = [[live[0]["start"], live[0]["end"]]]
    for w in live[1:]:
        gap = w["start"] - spans[-1][1]
        if gap <= keep_gap:
            spans[-1][1] = w["end"]
        elif gap <= demo_gap:
            # hesitation / "eee" / napas -> potong keras (span baru)
            spans.append([w["start"], w["end"]])
        else:
            # gap panjang: demo piano kalau ga hening -> sambung; kalau hening -> putus
            if silence_overlap(spans[-1][1], w["start"], silences, dur) >= 0.55:
                spans.append([w["start"], w["end"]])
            else:
                spans[-1][1] = w["end"]

    # --- 3. padding + clamp
    segs = [[max(0.0, s - pad), min(dur, e + pad)] for s, e in spans]

    # --- 4. buang filler yang kelindes padding
    segs = subtract(segs, filler_kills)

    # --- 5. merge yang deket, buang yang kependekan
    segs.sort()
    merged = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    final = [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= min_clip]
    return final, dropped


def extract_segment(src, start, end, out_path):
    run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-c:a", "aac", "-b:a", "192k", "-ar", "48000", str(out_path)])


def render(src, segments, out_path, tmpdir):
    tmpdir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (s, e) in enumerate(segments, 1):
        p = tmpdir / f"seg_{i:04d}.mp4"
        extract_segment(src, s, e, p)
        parts.append(p)
    lst = tmpdir / "concat_list.txt"
    with open(lst, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p.resolve().as_posix()}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(out_path)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("transcript")
    ap.add_argument("-o", "--output")
    ap.add_argument("--noise", default="-32dB",
                    help="ambang 'hening' buat nentuin gap panjang itu demo piano "
                         "(kept) atau dead-air (cut). JANGAN terlalu tinggi atau "
                         "decay antar nota piano ke-anggep hening. default -32dB")
    ap.add_argument("--min-silence", type=float, default=0.30)
    ap.add_argument("--keep-gap", type=float, default=0.45,
                    help="gap antar kata <= ini = ritme natural, ga dipotong (dtk)")
    ap.add_argument("--demo-gap", type=float, default=3.0,
                    help="gap > ini dianggap demo piano; di antara keep-gap dan ini = 'eee'/napas -> potong keras")
    ap.add_argument("--pad", type=float, default=0.15)
    ap.add_argument("--min-clip", type=float, default=0.40)
    ap.add_argument("--merge-gap", type=float, default=0.25)
    ap.add_argument("--retake-sim", type=float, default=0.78)
    ap.add_argument("--no-drop-retakes", action="store_true",
                    help="retake cuma dilaporin, ga dipotong")
    ap.add_argument("--keep-fillers", action="store_true")
    ap.add_argument("--patterns", default="interaction_patterns.txt")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--normalize-volume", action="store_true",
                    help="samakan volume akhir ke target loudness")
    ap.add_argument("--target-lufs", type=float, default=-16.0,
                    help="target volume LUFS (default -16 untuk YouTube)")
    args = ap.parse_args()

    src = Path(args.input)
    tr = json.load(open(args.transcript, encoding="utf-8"))
    out = Path(args.output) if args.output else src.with_name(f"{src.stem}_cut2s.mp4")
    noise = args.noise if args.noise.lower().endswith("db") or "." in args.noise else f"{args.noise}dB"

    dur = ffprobe_duration(src)
    words = load_words(tr)
    silences = detect_silences(src, noise, args.min_silence)
    print(f"Durasi {dur:.1f}s | {len(words)} kata | {len(silences)} span hening")

    segments, dropped = build_segments(
        words, silences, dur, args.keep_gap, args.demo_gap, args.pad,
        args.min_clip, args.merge_gap, drop_fillers=not args.keep_fillers)

    # --- retake: buang yang lebih pendek dari tiap pasangan kembar
    retakes = find_retake_pairs(tr, args.retake_sim)
    retake_kills = []
    if retakes:
        tag = "DIBUANG" if not args.no_drop_retakes else "cek manual"
        print(f"\n[retake] {len(retakes)} pasangan kalimat kembar ({tag}):")
        for a, b, r in retakes:
            # default: keep take TERAKHIR (b) — biasanya paling settle/lengkap
            # (lihat EDITOR_BRIEF). kecuali take awal jauh lebih panjang (>1.6x).
            if (a["end"] - a["start"]) > 1.6 * (b["end"] - b["start"]):
                drop, keep = b, a
            else:
                drop, keep = a, b
            print(f"  sim {r} | buang {drop['start']:.1f}-{drop['end']:.1f}"
                  f"  keep {keep['start']:.1f}-{keep['end']:.1f}")
            print(f"     drop: {drop['text'].strip()}")
            print(f"     keep: {keep['text'].strip()}")
            if not args.no_drop_retakes:
                retake_kills.append([drop["start"] - 0.05, drop["end"] + 0.10])

    # --- interaksi penonton / QnA
    pats = load_interaction_patterns(args.patterns)
    inter_kills = []
    for seg in tr["segments"]:
        txt = seg["text"].strip()
        if any(p.search(txt) for p in pats):
            inter_kills.append([seg["start"] - 0.05, seg["end"] + 0.10])
            print(f"\n[interaksi] buang {seg['start']:.1f}-{seg['end']:.1f}: {txt}")
    if not inter_kills:
        print("\n[interaksi] ga ada baris interaksi/QnA yang match pola.")

    segments = subtract(segments, retake_kills + inter_kills)
    segments.sort()
    merged = []
    for s, e in segments:
        if merged and s - merged[-1][1] <= args.merge_gap:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    segments = [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= args.min_clip]

    kept = sum(e - s for s, e in segments)
    print(f"\nSegmen kepake: {len(segments)}  ->  {kept:.1f}s "
          f"(hemat {dur-kept:.1f}s / {100*(dur-kept)/dur:.0f}%)")
    if dropped:
        print(f"Filler token dibuang ({len(dropped)}): " +
              ", ".join(f"{d['w']}@{d['start']:.1f}" for d in dropped[:25]))

    cuts_json = out.with_suffix(".cuts.json")
    json.dump([{"name": out.stem, "clips": [list(s) for s in segments]}],
              open(cuts_json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"-> {cuts_json}")

    if args.json_only:
        return
    if not segments:
        sys.exit("Ga ada segmen — longgarin --demo-gap / --keep-gap.")
    print("\n=== Render ===")
    render(src, segments, out, out.with_name(f"_{out.stem}_tmp"))
    if args.normalize_volume:
        from normalize_audio import normalize
        normalized = out.with_name(f"{out.stem}_normalizing{out.suffix}")
        print(f"\n=== Normalisasi volume ({args.target_lufs} LUFS) ===")
        normalize(out, normalized, target_i=args.target_lufs)
        normalized.replace(out)
    print(f"\nSelesai -> {out}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nffmpeg gagal: {e}")

