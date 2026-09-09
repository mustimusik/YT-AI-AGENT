# YT AI Agent

Satu pintu masuk untuk tiga jenis edit video:

- **YOUTUBE CUT**: merapikan rekaman yang sudah ada.
- **ADS VIDEO**: menghasilkan iklan dengan caption, zoom, B-roll, slide, dan CTA.
- **CLIPPER VIDEO**: mengubah percakapan atau workshop menjadi klip vertikal yang utuh konteksnya, dengan subtitle dan framing rapi.

Jalankan ini terlebih dahulu. Program akan menanyakan jenis video yang ingin diproses:

```powershell
py -3 run.py
```

Untuk agent/chat yang memakai repositori ini, instruksi routing ada di `AGENTS.md`: agent wajib menanyakan pilihan YOUTUBE CUT, ADS VIDEO, atau CLIPPER VIDEO sebelum mulai mengedit.

## Pipeline Clipper Video

Flow ini dipakai untuk video percakapan, workshop, atau Q&A panjang yang ingin diubah menjadi satu atau beberapa klip vertikal.

- Bila script sudah diberikan dan sudah di-ACC, langsung render mengikuti script tersebut.
- Bila belum ada script, buat transkrip dan draft dulu. Render hanya setelah script di-ACC.
- Satu klip Q&A mengikuti satu penanya dan menjawab semua pokok pertanyaannya; penanya berikutnya menjadi klip terpisah.
- Buang dead air dan footage saat kamera berpindah. Potongan dimulai saat kamera sudah settle pada pembicara.
- Subtitle putih per frasa, shadow gelap, sekitar tengah frame; gunakan gradasi gelap tipis di tepi atas dan bawah.

Panduan, format plan, dan perintah manual ada di [clipper-video/README.md](clipper-video/README.md).

## Pipeline YouTube

Toolkit untuk merapikan video pembelajaran/talking-head dengan FFmpeg:

- menghapus dead air atau mempercepatnya;
- memotong filler word, retake, dan segmen interaksi/Q&A berdasarkan transkrip;
- menyamakan volume akhir dengan EBU R128 / loudness normalization;
- memotong serta menggabungkan beberapa klip.

## Prasyarat

Pasang FFmpeg dan Python 3.11+ lalu pastikan keduanya tersedia di terminal:

```powershell
ffmpeg -version
py -3 --version
```

Untuk mode seleksi konten berbasis transkrip:

```powershell
py -3 -m pip install -r requirements.txt
```

## Pemakaian cepat

Hilangkan jeda hening dan ratakan volume:

```powershell
py -3 video-tools/autocut.py input.mp4 -o hasil.mp4 --normalize-volume
```

Untuk memilih konten secara lebih cerdas, buat transkrip dahulu lalu jalankan perencana cut:

```powershell
py -3 video-tools/transcribe.py input.mp4 transcript.json --model small --lang id
py -3 video-tools/cutplan.py input.mp4 transcript.json -o hasil.mp4 --normalize-volume
```

Sebelum merender, gunakan `--json-only` untuk meninjau daftar potongan. Pola interaksi yang harus dibuang dapat diubah di `video-tools/interaction_patterns.txt`.

## Catatan kualitas

Deteksi dead air bekerja dari level audio. Seleksi filler, retake, dan interaksi bekerja dari transkrip word-level; tinjau file JSON terlebih dahulu untuk rekaman musik, dialog ramai, atau istilah yang sulit ditranskrip.

## Pipeline Ads

Panduan lengkap, format naskah, manifest B-roll, dan aturan gaya ada di [ad-editor/README.md](ad-editor/README.md). Pipeline Ads membuat EDL terlebih dahulu agar kamu dapat meninjau caption, beat, B-roll, dan CTA sebelum video akhir dirender.
