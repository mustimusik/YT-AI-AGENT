# Routing untuk satu chat

Saat pengguna meminta proses video tetapi belum menyebut jenisnya, tanya terlebih dahulu:

> Mau pilih **YOUTUBE CUT**, **ADS VIDEO**, atau **CLIPPER VIDEO**?

Setelah pengguna memilih, gunakan hanya alur yang sesuai:

- **YOUTUBE CUT**: gunakan `video-tools/`. Tujuannya merapikan rekaman yang sudah ada dengan membuang dead air, filler, retake, dan menyamakan volume.
- **ADS VIDEO**: gunakan `ad-editor/`. Tujuannya menghasilkan iklan dari talking-head, naskah, dan B-roll dengan caption, zoom, cutaway, slide, serta CTA.
- **CLIPPER VIDEO**: gunakan `clipper-video/`. Tujuannya membuat klip vertikal utuh dari percakapan atau workshop: pilih satu konteks, buang dead air dan perpindahan kamera, lalu beri subtitle dan framing yang rapi.

Jangan menjalankan beberapa alur pada satu video kecuali pengguna secara eksplisit meminta proses dua tahap. Tinjau file JSON cut/EDL/clipper plan sebelum render final bila tersedia.

## Aturan CLIPPER VIDEO

1. Bila pengguna memberi script yang sudah di-ACC, langsung ikuti script dan lanjutkan edit.
2. Bila belum ada script, transkripsikan video lalu ajukan draft berisi hook, konteks, kutipan bertimestamp, dan batas klip. Tunggu ACC eksplisit sebelum render.
3. Dalam Q&A, satu klip mengikuti satu penanya sampai semua bagian pertanyaannya terjawab. Jangan menghilangkan pertanyaan ABRSM, sertifikasi, atau subtopik lain dari penanya yang sama hanya demi durasi pendek. Pisahkan penanya berikutnya ke klip lain.
4. Pertahankan interaksi yang membangun konteks klip. Jangan memakai pola pemotongan Q&A otomatis dari `video-tools/cutplan.py` untuk flow ini.
5. Buang dead air konservatif dan seluruh footage saat kamera berpindah atau belum stabil. Jangan memotong di tengah kata; masuk kembali saat kamera sudah settle ke pembicara.
6. CLIPPER VIDEO memiliki dua format: **Clipper 1 Tingkat** memakai satu frame; **Clipper 2 Tingkat** memakai layar split ketika penanya berbicara—penjawab di atas dan penanya di bawah—kemudian kembali satu frame saat jawaban dimulai.
7. Untuk Clipper 2 Tingkat, tanya dahulu apakah user memiliki foto/video penjawab untuk panel atas. Jika tidak ada, gunakan cuplikan penjawab dari video sumber ketika kamera sudah settle dan penjawab diam/mendengar pertanyaan.
8. Ajukan judul sebelum render dan tunggu ACC judul. Tampilkan judul merah dengan teks putih selama penanya berbicara, lalu hilangkan saat jawaban dimulai. Semua format memakai subtitle kuning tebal per frasa, outline/shadow hitam, sekitar tengah frame, serta gradasi hitam tipis di tepi atas dan bawah.
9. Target durasi hasil vertikal Clipper 1 Tingkat dan Clipper 2 Tingkat adalah sekitar 60 detik. Jika pertanyaan atau jawaban terlalu panjang, ambil kalimat yang paling penting tanpa menghilangkan pokok pertanyaan atau jawaban yang dibutuhkan.
