# autocut.py — Auto "cut2" (jump-cut / buang hening)

Kasih satu video, script-nya otomatis mendeteksi bagian hening/dead-air dan
memotongnya jadi jump-cut yang rapet. Cuma butuh **ffmpeg + ffprobe + Python**
(stdlib, tanpa Whisper / package tambahan).

## Pakai

```bash
py -3 autocut.py input.mp4
# -> input_cut2.mp4  + input_cut2.cuts.json
```

Opsi yang sering dipakai:

| flag | default | fungsi |
|---|---|---|
| `-o out.mp4` | `<input>_cut2.mp4` | nama output |
| `--noise` | `-30dB` | ambang hening. Lebih ke `-40dB` = cuma bener-bener sunyi yg dipotong; `-24dB` = lebih agresif |
| `--min-silence` | `0.35` | hening minimal (dtk) biar dianggap titik potong |
| `--pad` | `0.08` | sisa napas (dtk) di tiap sisi bicara — naikin kalau kepotong kepepet |
| `--min-clip` | `0.30` | buang remahan clip lebih pendek dari ini |
| `--merge-gap` | `0.20` | gabung 2 clip kalau jeda di antaranya <= ini |
| `--json-only` | – | cuma analisa + tulis `.cuts.json`, ga render |
| `--keep-silent-speed 6` | – | hening TIDAK dibuang, tapi di-fast-forward 6x (gaya jumpcutter) |

## Output `.cuts.json`

Formatnya sama persis dengan `cut_config.json` di pipeline editing
(`[{ "name", "clips": [[start,end], ...] }]`), jadi bisa langsung dipakai ulang
buat re-render atau di-edit manual dulu sebelum final.

## Alur di dalam

1. `ffmpeg silencedetect` → daftar `(silence_start, silence_end)`.
2. Komplemennya = segmen "kepake" → dikasih padding → buang yg kependekan →
   gabung yg jaraknya deket.
3. Tiap segmen di-extract ulang (re-encode `libx264 crf 18` / `aac 48k`,
   frame-accurate) lalu di-concat demuxer (`-c copy`).

Stream-copy sengaja tidak dipakai: footage talking-head GOP-nya panjang
(8+ dtk antar keyframe) jadi potongnya bakal nyangkut jauh dari titik minta.

## Rencana lanjutan (belum)

- Deteksi filler word ("umm", "eee") & retake berulang lewat transkrip Whisper
  (butuh `openai-whisper` / `faster-whisper`) — ini yang di EDITOR_BRIEF.md
  disebut "auto-detect titik potong".
- Gabung ke pipeline: setelah `autocut`, lempar `.cuts.json` ke tahap
  crop-muka / subtitle / zoom-punch.


