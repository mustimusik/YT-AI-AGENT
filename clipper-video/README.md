# Clipper Video

Flow untuk mengubah percakapan, workshop, atau Q&A panjang menjadi klip vertikal yang punya konteks utuh.

## Alur wajib

1. Bila user memberi script yang sudah di-ACC, masukkan script itu sebagai plan dan render langsung.
2. Bila user belum memberi script, transkripsikan dulu lalu buat draft. Tunggu ACC sebelum render.
3. Untuk Q&A, satu klip mengikuti satu penanya hingga semua pertanyaan penanya tersebut selesai dijawab. Jangan gabungkan penanya berikutnya.
4. Hapus dead air secara konservatif. Hapus perpindahan kamera dan mulai kembali ketika kamera sudah settle; jangan memotong di tengah kata.
5. Render dengan subtitle putih per frasa, shadow hitam, sekitar tengah frame, serta gradasi gelap tipis di atas dan bawah.

## Draft tanpa script

```powershell
py -3 video-tools/transcribe.py input.mp4 output/transcript.json --model small --lang id
py -3 clipper-video/clipper.py draft --video input.mp4 --transcript output/transcript.json --out output/draft.json
```

Tinjau `draft.json`, pilih satu konteks, isi `clips` dan `captions`, lalu set `approved` menjadi `true` setelah user ACC. Gunakan [script.example.json](script.example.json) sebagai formatnya.

## Render script yang sudah di-ACC

```powershell
py -3 clipper-video/clipper.py prepare --video input.mp4 --script script-approved.json --out output/clipper_plan.json
py -3 clipper-video/clipper.py render --plan output/clipper_plan.json --out output/final.mp4
```

`camera_settled` harus `true` untuk setiap clip. Renderer akan menolak plan yang belum `approved: true`, belum punya caption, atau memasukkan footage sebelum kamera settle.
