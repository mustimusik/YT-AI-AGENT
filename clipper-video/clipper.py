#!/usr/bin/env python3
"""Prepare and render a reviewed, one-context vertical clip plan."""
import argparse
import json
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stamp(seconds, srt=False):
    units = 1000 if srt else 100
    total = round(seconds * units)
    seconds, fraction = divmod(total, units)
    minutes, second = divmod(seconds, 60)
    hour, minute = divmod(minutes, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d},{fraction:03d}" if srt else f"{hour}:{minute:02d}:{second:02d}.{fraction:02d}"


def make_gradient(path, width=720, height=1280):
    rows = []
    for y in range(height):
        top = max(0, 1 - y / 150) ** 2 * 0.23
        bottom = max(0, 1 - (height - 1 - y) / 210) ** 2 * 0.30
        rows.append(b"\x00" + bytes((0, 0, 0, round(255 * max(top, bottom)))) * width)

    def chunk(kind, content):
        return (struct.pack(">I", len(content)) + kind + content +
                struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF))

    data = (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    path.write_bytes(data)


def normalized_plan(video, script):
    clipper_format = script.get("format", "single")
    if clipper_format not in {"single", "split_qa"}:
        raise ValueError("format harus single atau split_qa.")
    clips = script.get("clips") or []
    captions = script.get("captions") or []
    if not clips:
        raise ValueError("Script harus memiliki minimal satu clips: [{start, end}].")
    for clip in clips:
        if float(clip["end"]) <= float(clip["start"]):
            raise ValueError("Setiap clip harus memiliki end lebih besar dari start.")
        if clip.get("camera_settled") is False:
            raise ValueError("Jangan masukkan clip ketika kamera belum settle.")
        if clipper_format == "split_qa" and clip.get("role") not in {"question", "answer"}:
            raise ValueError("Format split_qa membutuhkan role question atau answer di setiap clip.")
    if script.get("approved") is not True:
        raise ValueError("Script belum ditandai approved: true. Render ditahan sampai ACC.")
    if script.get("title_approved") is not True:
        raise ValueError("Judul belum di-ACC. Set title_approved ke true setelah user setuju.")
    total_duration = sum(float(clip["end"]) - float(clip["start"]) for clip in clips)
    if total_duration > 65:
        raise ValueError("Durasi clip lebih dari 65 detik. Padatkan ke sekitar 60 detik sambil menjaga semua pokok pertanyaan terjawab.")
    if clipper_format == "split_qa":
        question_clips = [clip for clip in clips if clip.get("role") == "question"]
        if not question_clips:
            raise ValueError("Format split_qa membutuhkan minimal satu clip dengan role question.")
        if not script.get("responder_asset") and not script.get("responder_wait"):
            raise ValueError("Format split_qa membutuhkan responder_asset atau responder_wait untuk layar atas.")
    style = {"caption_position_y": 627, "caption_font_size": 48,
             "caption_color": "yellow", "caption_bold": True, "caption_shadow": "black",
             "title_color": "white", "title_background": "red", "title_position_y": 500,
             "edge_gradient": True, "target": "vertical_720x1280"}
    if clipper_format == "split_qa":
        style.update({"title_position_y": 500})
    return {
        "version": 1,
        "approved": True,
        "format": clipper_format,
        "source": str(Path(video).resolve()),
        "title": script.get("title", "Clipper Video"),
        "context": script.get("context", "Satu konteks percakapan."),
        "speaker": script.get("speaker", ""),
        "clips": clips,
        "captions": captions,
        "title_approved": script.get("title_approved", False),
        "responder_asset": script.get("responder_asset"),
        "responder_wait": script.get("responder_wait"),
        "style": style,
    }


def draft(args):
    transcript = json.loads(Path(args.transcript).read_text(encoding="utf-8"))
    segments = transcript.get("segments", [])
    plan = {
        "version": 1,
        "approved": False,
        "format": args.format,
        "title_approved": False,
        "source": str(Path(args.video).resolve()),
        "title": "DRAFT — isi setelah memilih satu konteks",
        "context": "Pilih satu penanya atau satu ide yang utuh. Untuk Q&A, jawab seluruh pokok pertanyaan penanya tersebut.",
        "speaker": "",
        "clips": [],
        "captions": [],
        "review_notes": [
            "Pilih hanya satu penanya/konteks dalam satu plan.",
            "Masukkan semua jawaban untuk pokok pertanyaan penanya itu, termasuk subtopik seperti ABRSM atau sertifikasi.",
            "Tandai hanya potongan dengan kamera sudah settle: camera_settled: true.",
            "Target total durasi sekitar 60 detik; padatkan pertanyaan dan jawaban panjang ke bagian yang paling penting.",
            "Kelompokkan subtitle per frasa, bukan per kata.",
            "Ajukan judul merah-putih kepada user. Set title_approved dan approved ke true hanya setelah user memberi ACC.",
            "Untuk Q&A, beri role question pada potongan penanya dan role answer pada potongan penjawab. Judul tampil selama question lalu hilang ketika answer dimulai.",
            "Subtitle kuning tebal dengan outline hitam."
        ],
        "transcript_segments": [
            {"start": item.get("start"), "end": item.get("end"), "text": item.get("text", "")}
            for item in segments
        ],
    }
    if args.format == "split_qa":
        plan.update({
            "title_approved": False,
            "responder_asset": args.responder_asset or None,
            "responder_wait": None,
            "review_notes": plan["review_notes"] + [
                "Tanya dulu apakah user memiliki foto/video penjawab untuk layar atas.",
                "Jika tidak ada, isi responder_wait: {start, end} dari video sumber ketika penjawab diam dan kamera sudah settle.",
                "Setiap clip harus memiliki role question atau answer. Hanya role question yang split dua tingkat.",
                "Ajukan judul merah-putih kepada user dan set title_approved ke true hanya setelah ACC.",
                "Untuk format ini, subtitle kuning tebal dengan outline hitam."
            ]
        })
    write_json(Path(args.out), plan)
    print(f"Draft dibuat: {args.out}")


def prepare(args):
    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    write_json(Path(args.out), normalized_plan(args.video, script))
    print(f"Plan siap dirender: {args.out}")


def render(args):
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    if plan.get("approved") is not True:
        raise ValueError("Plan belum di-ACC.")
    source = Path(plan["source"])
    if not source.exists():
        raise FileNotFoundError(f"Video sumber tidak ditemukan: {source}")
    output = Path(args.out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    clips = plan["clips"]
    clipper_format = plan.get("format", "single")
    captions = plan.get("captions", [])
    timeline, cursor = [], 0.0
    for clip in clips:
        start, end = float(clip["start"]), float(clip["end"])
        duration = round((end - start) * 30) / 30
        timeline.append((start, duration, cursor))
        cursor += duration
    if not captions:
        raise ValueError("Plan belum memiliki captions per frasa.")

    with tempfile.TemporaryDirectory(prefix="clipper-") as temp:
        work = Path(temp)
        parts = []
        for index, (start, duration, _) in enumerate(timeline):
            part = work / f"part_{index:02d}.mp4"
            clip = clips[index]
            if clipper_format == "split_qa" and clip.get("role") == "question":
                top_source = plan.get("responder_asset")
                wait = plan.get("responder_wait") or {}
                top_is_asset = bool(top_source)
                if top_is_asset:
                    top_path = Path(top_source)
                    if not top_path.exists():
                        raise FileNotFoundError(f"Asset penjawab tidak ditemukan: {top_path}")
                    top_input = ["-loop", "1", "-i", str(top_path)] if top_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"} else ["-i", str(top_path)]
                else:
                    top_input = ["-ss", str(float(wait["start"])), "-i", str(source)]
                command = [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2",
                    "-ss", str(start), "-i", str(source), *top_input, "-t", str(duration),
                    "-filter_complex",
                    "[0:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640[bottom];"
                    "[1:v]scale=720:640:force_original_aspect_ratio=increase,crop=720:640[top];"
                    "[top][bottom]vstack=inputs=2[v]", "-map", "[v]", "-map", "0:a:0",
                    "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "160k", str(part)
                ]
            else:
                command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2",
                "-ss", str(start), "-i", str(source), "-t", str(duration),
                "-map", "0:v:0", "-map", "0:a:0", "-vf", "scale=720:1280:flags=lanczos,setsar=1",
                "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-b:a", "160k", str(part)
                ]
            subprocess.run(command, check=True)
            parts.append(part)
        concat = work / "concat.txt"
        concat.write_text("".join(f"file '{part.as_posix()}'\n" for part in parts), encoding="utf-8")
        assembled = work / "assembled.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                        "-safe", "0", "-i", str(concat), "-c", "copy", str(assembled)], check=True)
        events = []
        for item in captions:
            source_start, source_end = float(item["start"]), float(item["end"])
            for section_start, duration, out_start in timeline:
                left, right = max(source_start, section_start), min(source_end, section_start + duration)
                if right > left:
                    events.append((out_start + left - section_start, out_start + right - section_start, item["text"]))
        if not events:
            raise ValueError("Tidak ada caption yang berada pada potongan video.")
        ass = work / "subtitles.ass"
        is_split = clipper_format == "split_qa"
        caption_color = "&H0000FFFF"
        caption_bold = "1"
        caption_y = int(plan["style"].get("caption_position_y", 627))
        title_size = int(plan["style"].get("title_font_size", 34))
        header = f"""[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,{plan['style'].get('caption_font_size', 48)},{caption_color},{caption_color},&H80000000,&H35000000,{caption_bold},0,0,0,100,100,0,0,1,1.2,2.5,5,42,42,0,1\nStyle: Title,Arial,{title_size},&H00FFFFFF,&H00FFFFFF,&H000000FF,&H000000FF,1,0,0,0,100,100,0,0,3,2,0,5,28,28,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
        lines = []
        for start, end, text in events:
            ass_text = text.replace("\n", r"\N")
            lines.append(
                f"Dialogue: 0,{stamp(start)},{stamp(end)},Default,,0,0,0,,{{\\pos(360,{caption_y})}}{ass_text}\n"
            )
        first_answer = next((out_start for item, (_, _, out_start) in zip(clips, timeline)
                             if item.get("role") == "answer"), cursor)
        title_end = min(first_answer, cursor)
        if title_end > 0:
            title = plan["title"].replace("\n", r"\N")
            title_y = int(plan["style"].get("title_position_y", 500))
            lines.append(f"Dialogue: 1,{stamp(0)},{stamp(title_end)},Title,,0,0,0,,{{\\pos(360,{title_y})}}{title}\n")
        ass.write_text(header + "".join(lines), encoding="utf-8-sig")
        gradient = work / "gradient.png"
        make_gradient(gradient)
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2",
            "-i", str(assembled), "-i", str(gradient), "-filter_complex",
            "[0:v][1:v]overlay=0:0:format=auto,ass=subtitles.ass[v]", "-map", "[v]", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(output)
        ], cwd=work, check=True)
    print(f"Selesai: {output} ({cursor:.2f} detik)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    draft_parser = sub.add_parser("draft")
    draft_parser.add_argument("--video", required=True)
    draft_parser.add_argument("--transcript", required=True)
    draft_parser.add_argument("--out", required=True)
    draft_parser.add_argument("--format", choices=["single", "split_qa"], default="single")
    draft_parser.add_argument("--responder-asset")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--video", required=True)
    prepare_parser.add_argument("--script", required=True)
    prepare_parser.add_argument("--out", required=True)
    render_parser = sub.add_parser("render")
    render_parser.add_argument("--plan", required=True)
    render_parser.add_argument("--out", required=True)
    args = parser.parse_args()
    {"draft": draft, "prepare": prepare, "render": render}[args.command](args)


if __name__ == "__main__":
    main()
