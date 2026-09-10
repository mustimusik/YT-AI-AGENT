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


def clipper():
    video = ask("Lokasi file video")
    out_dir = Path(ask("Folder output", "clipper-output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    format_choice = ask("Pilih format: 1 = Clipper 1 Tingkat, 2 = Clipper 2 Tingkat split Q&A", "1")
    if format_choice not in {"1", "2"}:
        raise ValueError("Pilih 1 untuk Clipper 1 Tingkat atau 2 untuk Clipper 2 Tingkat.")
    clipper_format = "single" if format_choice == "1" else "split_qa"
    responder_asset = None
    if clipper_format == "split_qa":
        responder_asset = ask("Lokasi foto/video penjawab untuk layar atas (kosongkan bila ingin cuplikan dari video asli)")
    has_script = ask("Sudah ada script yang di-ACC? ketik ya atau tidak", "tidak").lower()
    transcript = out_dir / "transcript.json"
    plan = out_dir / "clipper_plan.json"
    if has_script in {"ya", "y", "yes"}:
        script = ask("Lokasi script JSON yang sudah di-ACC")
        execute([sys.executable, ROOT / "clipper-video" / "clipper.py", "prepare",
                 "--video", video, "--script", script, "--out", plan])
        print(f"\nRencana render dibuat di {plan}. Karena script sudah di-ACC, lanjutkan dengan mode render setelah mengecek file.")
        if ask("Render sekarang? ketik ya untuk lanjut", "tidak").lower() in {"ya", "y", "yes"}:
            execute([sys.executable, ROOT / "clipper-video" / "clipper.py", "render",
                     "--plan", plan, "--out", out_dir / "final.mp4"])
        return
    execute([sys.executable, ROOT / "video-tools" / "transcribe.py", video, transcript,
             "--model", "small", "--lang", "id"])
    command = [sys.executable, ROOT / "clipper-video" / "clipper.py", "draft",
               "--video", video, "--transcript", transcript, "--out", plan, "--format", clipper_format]
    if responder_asset:
        command.extend(["--responder-asset", responder_asset])
    execute(command)
    print(f"\nDraft script dibuat di {plan}. Tinjau konteks dan ACC judul/script dulu; jangan render sebelum ACC.")


def main():
    print("=== YT AI Agent ===")
    print("1. YOUTUBE CUT — rapikan dead air, filler, retake, volume")
    print("2. ADS VIDEO — caption, zoom, B-roll, CTA")
    print("3. CLIPPER VIDEO — 1 tingkat atau split Q&A 2 tingkat")
    choice = ask("Mau pilih yang mana")
    try:
        if choice == "1":
            youtube()
        elif choice == "2":
            ads()
        elif choice == "3":
            clipper()
        else:
            raise ValueError("Pilih 1 untuk YOUTUBE CUT, 2 untuk ADS VIDEO, atau 3 untuk CLIPPER VIDEO.")
    except subprocess.CalledProcessError as error:
        sys.exit(f"Proses berhenti: {error}")


if __name__ == "__main__":
    main()
