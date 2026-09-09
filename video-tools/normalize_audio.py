#!/usr/bin/env python3
"""Normalisasi loudness video/audio memakai FFmpeg loudnorm dua tahap."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs)


def measured_values(source, target_i, target_lra, target_tp):
    command = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(source),
        "-af", f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:print_format=json",
        "-f", "null", "-",
    ]
    result = run(command)
    match = re.search(r"\{\s*\"input_i\".*?\}", result.stderr, re.S)
    if not match:
        raise RuntimeError("FFmpeg tidak mengembalikan hasil analisis loudness.")
    return json.loads(match.group(0))


def normalize(source, output, target_i=-16.0, target_lra=11.0, target_tp=-1.5):
    values = measured_values(source, target_i, target_lra, target_tp)
    filt = (
        f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:"
        f"measured_I={values['input_i']}:measured_LRA={values['input_lra']}:"
        f"measured_TP={values['input_tp']}:measured_thresh={values['input_thresh']}:"
        f"offset={values['target_offset']}:linear=true:print_format=summary"
    )
    command = [
        "ffmpeg", "-y", "-i", str(source), "-map", "0:v?", "-map", "0:a?",
        "-c:v", "copy", "-af", filt, "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description="Sejajarkan volume audio video.")
    parser.add_argument("input")
    parser.add_argument("-o", "--output")
    parser.add_argument("--target-lufs", type=float, default=-16.0)
    parser.add_argument("--true-peak", type=float, default=-1.5)
    args = parser.parse_args()
    source = Path(args.input)
    if not source.exists():
        sys.exit(f"File tidak ditemukan: {source}")
    output = Path(args.output) if args.output else source.with_name(source.stem + "_normalized.mp4")
    normalize(source, output, args.target_lufs, 11.0, args.true_peak)
    print(f"Selesai: {output}")


if __name__ == "__main__":
    main()
