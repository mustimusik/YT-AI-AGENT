#!/usr/bin/env python3
"""
Cut clips from one or more (YouTube) videos at given timestamps and merge
them into a single output video, in the order listed.

Usage:
    python clip_merge.py config.txt output.mp4

config.txt format (one clip per line, in merge order):
    <url_or_local_path> <start> <end> [label]

Timestamps accept HH:MM:SS, MM:SS, or seconds.
Lines starting with # are ignored. Blank lines are ignored.

Example:
    https://www.youtube.com/watch?v=InRQa5KGVOw 17:14 24:44 pattern1
    https://www.youtube.com/watch?v=6aZ71FrTnXM 23:08 25:21 pattern2
"""
import os
import re
import sys
import subprocess
import hashlib
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, "_source_cache")
CLIPS_DIR = os.path.join(SCRIPT_DIR, "_clips")


def parse_timestamp(ts):
    ts = ts.strip()
    parts = ts.split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def is_url(s):
    return re.match(r"^https?://", s.strip()) is not None


def url_hash(url):
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def download_source(url):
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = url_hash(url)
    # Only trust a final merged output (key.mp4). Ignore fragments like
    # key.f140.m4a, key.f299.mp4.part etc, which mean a prior download
    # never completed/merged.
    final_path = os.path.join(CACHE_DIR, key + ".mp4")
    if os.path.exists(final_path):
        print(f"  [cache] using already-downloaded source: {final_path}")
        return final_path

    # clean up any leftover partial/fragment files from a failed attempt
    for f in os.listdir(CACHE_DIR):
        if f.startswith(key + ".") and f != key + ".mp4":
            os.remove(os.path.join(CACHE_DIR, f))

    out_template = os.path.join(CACHE_DIR, key + ".%(ext)s")
    print(f"  [download] {url}")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "--merge-output-format", "mp4",
        "-o", out_template,
        url,
    ]
    subprocess.run(cmd, check=True)

    matches = [f for f in os.listdir(CACHE_DIR) if f.startswith(key + ".")]
    if not matches:
        raise RuntimeError(f"yt-dlp did not produce an output file for {url}")
    return os.path.join(CACHE_DIR, matches[0])


def cut_clip(source_path, start, end, out_path):
    duration = end - start
    if duration <= 0:
        raise ValueError(f"end ({end}) must be after start ({start})")
    print(f"  [cut] {os.path.basename(source_path)} {start:.2f}s -> {end:.2f}s")
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", source_path,
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-avoid_negative_ts", "make_zero",
        out_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def merge_clips(clip_paths, output_path):
    print(f"  [merge] {len(clip_paths)} clips -> {output_path}")
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in clip_paths:
            escaped = p.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_file = f.name
    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_file,
            "-c", "copy",
            output_path,
        ]
        subprocess.run(cmd, check=True)
    finally:
        os.remove(list_file)


def main():
    if len(sys.argv) != 3:
        print("Usage: python clip_merge.py <config.txt> <output.mp4>")
        sys.exit(1)

    config_path, output_path = sys.argv[1], sys.argv[2]
    os.makedirs(CLIPS_DIR, exist_ok=True)

    entries = []
    with open(config_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 3:
                print(f"Skipping malformed line {lineno}: {line}")
                continue
            src, start_s, end_s = parts[0], parts[1], parts[2]
            label = parts[3] if len(parts) > 3 else f"clip{lineno}"
            entries.append((src, start_s, end_s, label))

    if not entries:
        print("No clips found in config.")
        sys.exit(1)

    clip_paths = []
    for i, (src, start_s, end_s, label) in enumerate(entries, 1):
        print(f"[{i}/{len(entries)}] {label}")
        source_path = download_source(src) if is_url(src) else src
        if not os.path.exists(source_path):
            raise FileNotFoundError(source_path)

        start = parse_timestamp(start_s)
        end = parse_timestamp(end_s)
        clip_out = os.path.join(CLIPS_DIR, f"{i:03d}_{label}.mp4")
        cut_clip(source_path, start, end, clip_out)
        clip_paths.append(clip_out)

    merge_clips(clip_paths, output_path)
    print(f"\nDone. Output: {output_path}")


if __name__ == "__main__":
    main()


