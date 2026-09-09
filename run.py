#!/usr/bin/env python3
"""Satu pintu masuk interaktif untuk pipeline YouTube dan Ads."""
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def ask(label, default=None):
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def execute(command):
    print("\nMenjalankan:", " ".join(f'\"{part}\"' if " " in str(part) else str(part) for part in command))
    subprocess.run(command, check=True)


def youtube():
    video = ask("Lokasi file video")
    output = ask("Nama output", "hasil_youtube.mp4")
    mode = ask("Pilih proses: 1 = dead air + volume, 2 = seleksi pintar (filler, retake, Q&A)", "1")
    if mode == "1":
        execute([sys.executable, ROOT / "video-tools" / "autocut.py", video,
                 "-o", output, "--normalize-volume"])
        return
    if mode == "2":
        transcript = ask("File transkrip JSON (kosongkan untuk membuat baru)")
        if not transcript:
            transcript = str(Path(output).with_suffix(".transcript.json"))
            execute([sys.executable, ROOT / "video-tools" / "transcribe.py", video, transcript,
                     "--model", "small", "--lang", "id"])
        execute([sys.executable, ROOT / "video-tools" / "cutplan.py", video, transcript,
                 "-o", output, "--normalize-volume"])
        return
    raise ValueError("Pilihan proses harus 1 atau 2.")


def ads():
    video = ask("Lokasi video talking-head")
    script = ask("Lokasi naskah iklan")
    broll = ask("Lokasi manifest B-roll", str(ROOT / "ad-editor" / "broll_manifest.json"))
    out_dir = Path(ask("Folder output", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    words = out_dir / "words.json"
    edl = out_dir / "edl.json"
    output = out_dir / "final.mp4"
    execute([sys.executable, ROOT / "ad-editor" / "align.py", "--video", video,
             "--script", script, "--out", words])
    execute([sys.executable, ROOT / "ad-editor" / "plan.py", "--words", words,
             "--broll", broll, "--out", edl])
    print(f"\nRencana iklan dibuat di {edl}. Tinjau dulu sebelum render.")
    if ask("Render sekarang? ketik ya untuk lanjut", "tidak").lower() in {"ya", "y", "yes"}:
        execute([sys.executable, ROOT / "ad-editor" / "render.py", "--video", video,
                 "--edl", edl, "--out", output])


def main():
    print("=== YT AI Agent ===")
    print("1. YOUTUBE CUT — rapikan dead air, filler, retake, volume")
    print("2. ADS VIDEO — caption, zoom, B-roll, CTA")
    choice = ask("Mau pilih yang mana")
    try:
        if choice == "1":
            youtube()
        elif choice == "2":
            ads()
        else:
            raise ValueError("Pilih 1 untuk YOUTUBE CUT atau 2 untuk ADS VIDEO.")
    except subprocess.CalledProcessError as error:
        sys.exit(f"Proses berhenti: {error}")


if __name__ == "__main__":
    main()
