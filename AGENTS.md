# Routing untuk satu chat

Saat pengguna meminta proses video tetapi belum menyebut jenisnya, tanya terlebih dahulu:

> Mau pilih **YOUTUBE CUT** atau **ADS VIDEO**?

Setelah pengguna memilih, gunakan hanya alur yang sesuai:

- **YOUTUBE CUT**: gunakan `video-tools/`. Tujuannya merapikan rekaman yang sudah ada dengan membuang dead air, filler, retake, dan menyamakan volume.
- **ADS VIDEO**: gunakan `ad-editor/`. Tujuannya menghasilkan iklan dari talking-head, naskah, dan B-roll dengan caption, zoom, cutaway, slide, serta CTA.

Jangan menjalankan kedua alur pada satu video kecuali pengguna secara eksplisit meminta proses dua tahap. Tinjau file JSON cut/EDL sebelum render final bila tersedia.
