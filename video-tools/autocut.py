#!/usr/bin/env python3
"""
Auto "cut2" — potong otomatis bagian hening/dead-air dari sebuah video biar
jadi jump-cut yang rapet (mirip auto-editor / jumpcutter, tapi cuma butuh
ffmpeg + Python stdlib).

Flow:
  1. Deteksi bagian hening pakai ffmpeg `silencedetect`.
  2. Bikin daftar segmen "kepake" = komplemen dari hening, dikasih padding,
     buang remahan pendek, gabung segmen yang jaraknya deket.
  3. Render: tiap segmen di-extract ulang (re-encode, frame-accurate) lalu
     di-concat demuxer. Stream-copy sengaja TIDAK dipakai karena footage
     talking-head biasanya GOP-nya panjang (8+ dtk antar keyframe) jadi
     potongnya nyangkut jauh dari titik yang diminta.
  4. Nulis <output>.cuts.json dengan format yang sama kayak cut_local.py /
     cut_config.json ([{ "name", "clips": [[start,end], ...] }]) biar bisa
     langsung dipake ulang di pipeline editing yang udah ada.

Usage:
    python autocut.py input.mp4
    python autocut.py input.mov -o tight.mp4 --noise -30dB --min-silence 0.4 --pad 0.08
    python autocut.py input.mp4 --json-only          # cuma analisa, ga render
    python autocut.py input.mp4 --keep-silent-speed 6 # hening di-fast-forward, ga dibuang

Butuh: ffmpeg + ffprobe di PATH.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(cmd, **kw):
    print("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, check=True, **kw)


def parse_db(val):
    """'-30dB' / '-30' / '0.01' -> string yang diterima silencedetect."""
    v = str(val).strip()
    return v if v.lower().endswith("db") or "." in v else f"{v}dB"


def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def detect_silences(src, noise, min_silence):
    """Return list of (silence_start, silence_end) in detik."""
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(src),
         "-af", f"silencedetect=noise={noise}:d={min_silence}",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    log = proc.stderr
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", log)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", log)]
    spans = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        spans.append((max(0.0, s), e))
    return spans


def build_keep_segments(duration, silences, pad, min_clip, merge_gap):
    """Komplemen dari hening -> segmen kepake, dengan padding + merge + filter."""
    # 1. raw keep = gap antar hening
    keep = []
    cursor = 0.0
    for s, e in silences:
        if e is None:
            e = duration
        if s > cursor:
            keep.append([cursor, s])
        cursor = max(cursor, e)
    if cursor < duration:
        keep.append([cursor, duration])

    # 2. padding (makan sedikit ke dalam hening di dua sisi)
    padded = []
    for s, e in keep:
        padded.append([max(0.0, s - pad), min(duration, e + pad)])

    # 3. merge segmen yang jaraknya < merge_gap
    merged = []
    for seg in padded:
        if merged and seg[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = max(merged[-1][1], seg[1])
        else:
            merged.append(seg)

    # 4. buang segmen yang lebih pendek dari min_clip
    final = [seg for seg in merged if seg[1] - seg[0] >= min_clip]
    return [(round(s, 3), round(e, 3)) for s, e in final]


def extract_segment(src, start, end, out_path):
    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-i", str(src),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(out_path),
    ])


def concat_copy(parts, out_path, list_path):
    with open(list_path, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{Path(p).resolve().as_posix()}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_path),
         "-c", "copy", str(out_path)])


def render_reencode(src, segments, out_path, tmpdir):
    tmpdir.mkdir(parents=True, exist_ok=True)
    parts = []
    for i, (s, e) in enumerate(segments, 1):
        p = tmpdir / f"seg_{i:04d}.mp4"
        extract_segment(src, s, e, p)
        parts.append(p)
    concat_copy(parts, out_path, tmpdir / "concat_list.txt")


def render_speed_ramp(src, silences, out_path, duration, speed, noise, min_silence):
    """Alih-alih buang hening, percepat bagian hening `speed`x (jumpcutter-style).
    Pakai satu pass filter_complex (bisa berat buat video panjang)."""
    # keep-loud segments (tanpa padding) buat bikin PTS map
    loud = build_keep_segments(duration, silences, pad=0.0, min_clip=0.0,
                               merge_gap=0.0)
    v_parts, a_parts, idx = [], [], 0
    cursor = 0.0
    timeline = []
    for (ls, le) in loud:
        if ls > cursor:
            timeline.append(("silent", cursor, ls))
        timeline.append(("loud", ls, le))
        cursor = le
    if cursor < duration:
        timeline.append(("silent", cursor, duration))

    for kind, s, e in timeline:
        if e - s < 0.02:
            continue
        v = f"[0:v]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS"
        a = f"[0:a]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS"
        if kind == "silent":
            v += f",setpts=PTS/{speed}"
            atempo = speed
            chain = []
            while atempo > 2.0:
                chain.append("atempo=2.0")
                atempo /= 2.0
            chain.append(f"atempo={atempo:.4f}")
            a += "," + ",".join(chain)
        v_parts.append(f"{v}[v{idx}]")
        a_parts.append(f"{a}[a{idx}]")
        idx += 1

    concat_in = "".join(f"[v{i}][a{i}]" for i in range(idx))
    fc = ";".join(v_parts + a_parts) + f";{concat_in}concat=n={idx}:v=1:a=1[v][a]"
    run([
        "ffmpeg", "-y", "-i", str(src), "-filter_complex", fc,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(out_path),
    ])


def main():
    ap = argparse.ArgumentParser(description="Auto jump-cut / silence removal.")
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="default: <input>_cut2.mp4")
    ap.add_argument("--noise", default="-30dB",
                    help="ambang hening buat silencedetect (default -30dB)")
    ap.add_argument("--min-silence", type=float, default=0.35,
                    help="durasi minimal (dtk) sebuah hening biar dianggap potong (default 0.35)")
    ap.add_argument("--pad", type=float, default=0.08,
                    help="padding (dtk) yang disisain di tiap sisi bicara (default 0.08)")
    ap.add_argument("--min-clip", type=float, default=0.30,
                    help="buang segmen kepake yang lebih pendek dari ini (default 0.30)")
    ap.add_argument("--merge-gap", type=float, default=0.20,
                    help="gabung dua segmen kalau jeda di antaranya <= ini (default 0.20)")
    ap.add_argument("--keep-silent-speed", type=float, default=None,
                    help="kalau di-set, hening TIDAK dibuang tapi dipercepat Nx (mis. 6)")
    ap.add_argument("--json-only", action="store_true",
                    help="cuma analisa + tulis .cuts.json, ga render video")
    ap.add_argument("--normalize-volume", action="store_true",
                    help="samakan volume akhir ke target loudness")
    ap.add_argument("--target-lufs", type=float, default=-16.0,
                    help="target volume LUFS (default -16 untuk YouTube)")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"File ga ketemu: {src}")
    out = Path(args.output) if args.output else src.with_name(f"{src.stem}_cut2.mp4")
    noise = parse_db(args.noise)

    duration = ffprobe_duration(src)
    print(f"Durasi sumber: {duration:.2f}s ({duration/60:.1f} min)")

    print("\n=== Deteksi hening ===")
    silences = detect_silences(src, noise, args.min_silence)
    print(f"Ketemu {len(silences)} bagian hening (noise={noise}, d={args.min_silence})")

    segments = build_keep_segments(
        duration, silences, args.pad, args.min_clip, args.merge_gap
    )
    kept = sum(e - s for s, e in segments)
    print(f"\nSegmen kepake: {len(segments)}")
    print(f"Durasi setelah potong: {kept:.2f}s ({kept/60:.1f} min) "
          f"— hemat {duration - kept:.2f}s ({100*(duration-kept)/duration:.0f}%)")

    cuts_json = out.with_suffix(".cuts.json")
    with open(cuts_json, "w", encoding="utf-8") as f:
        json.dump([{"name": out.stem, "clips": [list(s) for s in segments]}],
                  f, ensure_ascii=False, indent=2)
    print(f"-> {cuts_json}  (format cut_local.py / cut_config.json)")

    if args.json_only:
        return
    if not segments:
        sys.exit("Ga ada segmen kepake — longgarin --noise atau --min-silence.")

    tmpdir = out.with_name(f"_{out.stem}_tmp")
    print(f"\n=== Render ({'speed-ramp' if args.keep_silent_speed else 'reencode'}) ===")
    if args.keep_silent_speed:
        render_speed_ramp(src, silences, out, duration,
                          args.keep_silent_speed, noise, args.min_silence)
    else:
        render_reencode(src, segments, out, tmpdir)

    if args.normalize_volume:
        from normalize_audio import normalize
        normalized = out.with_name(f"{out.stem}_normalizing{out.suffix}")
        print(f"\n=== Normalisasi volume ({args.target_lufs} LUFS) ===")
        normalize(out, normalized, target_i=args.target_lufs)
        normalized.replace(out)

    print(f"\nSelesai -> {out}")
    print(f"(file sementara di {tmpdir}/ — hapus manual kalau udah oke)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nffmpeg gagal: {e}")

