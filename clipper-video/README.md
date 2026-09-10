# Clipper Video

Flow untuk mengubah percakapan, workshop, atau Q&A panjang menjadi klip vertikal yang punya konteks utuh.

## Dua format

- **Clipper 1 Tingkat**: satu frame. Judul merah-putih tampil selama penanya berbicara lalu hilang ketika jawaban dimulai. Subtitle kuning tebal dengan outline/shadow hitam.
- **Clipper 2 Tingkat**: saat penanya berbicara, penjawab tampil di panel atas dan penanya di panel bawah. Saat jawaban dimulai, kembali ke Clipper 1 Tingkat. Judul dan subtitle memakai gaya yang sama.

Untuk Clipper 2 Tingkat, tanyakan dulu apakah user punya foto/video penjawab. Jika tidak, gunakan cuplikan penjawab dari video sumber saat ia diam dan kamera sudah settle.

## Alur wajib

1. Bila user memberi script yang sudah di-ACC, masukkan script itu sebagai plan dan render langsung.
2. Bila user belum memberi script, transkripsikan dulu lalu buat draft. Tunggu ACC sebelum render.
3. Untuk Q&A, satu klip mengikuti satu penanya hingga semua pertanyaan penanya tersebut selesai dijawab. Jangan gabungkan penanya berikutnya.
4. Hapus dead air secara konservatif. Hapus perpindahan kamera dan mulai kembali ketika kamera sudah settle; jangan memotong di tengah kata.
5. Ajukan judul terlebih dahulu. Render hanya setelah judul dan script di-ACC; judul merah dengan teks putih tampil selama pertanyaan lalu hilang saat jawaban mulai.
6. Render dengan subtitle kuning tebal per frasa, outline/shadow hitam, sekitar tengah frame, serta gradasi gelap tipis di atas dan bawah.
7. Target durasi hasil vertikal adalah sekitar 60 detik. Padatkan pertanyaan dan jawaban panjang ke bagian paling penting, sambil tetap menjaga semua pokok pertanyaan terjawab.

## Draft tanpa script

```powershell
py -3 video-tools/transcribe.py input.mp4 output/transcript.json --model small --lang id
py -3 clipper-video/clipper.py draft --video input.mp4 --transcript output/transcript.json --out output/draft.json --format single
```

Untuk split Q&A gunakan `--format split_qa`. Tambahkan `--responder-asset path/foto-atau-video.mp4` bila user punya aset penjawab. Jika tidak ada aset, isi `responder_wait` dari video sumber. Tinjau `draft.json`, pilih satu konteks, isi `clips` dan `captions`, lalu set `title_approved` dan `approved` menjadi `true` setelah user ACC. Gunakan [script.example.json](script.example.json) sebagai formatnya.

## Render script yang sudah di-ACC

```powershell
py -3 clipper-video/clipper.py prepare --video input.mp4 --script script-approved.json --out output/clipper_plan.json
py -3 clipper-video/clipper.py render --plan output/clipper_plan.json --out output/final.mp4
```

`camera_settled` harus `true` untuk setiap clip. Renderer akan menolak plan yang belum `approved: true`, belum punya caption, atau memasukkan footage sebelum kamera settle.
