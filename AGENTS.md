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
6. Render vertikal dengan subjek di tengah jika footage memungkinkan, subtitle putih per frasa sekitar tengah frame dengan shadow hitam, dan gradasi hitam tipis di tepi atas serta bawah.
