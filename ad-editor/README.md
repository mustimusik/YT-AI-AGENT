# AI Ad Editor — v1

A local pipeline that takes your talking-head footage + a script you already
wrote + a pool of b-roll, and produces an edited vertical ad in your style —
captions with accent colors, zoom-punches, b-roll cutaways, and big
number/offer "slides" — extracted from your 3 reference ads
(see `style_bible.md`).

**Status: v1 core is built and tested.** I validated the renderer end-to-end
against synthetic test footage (captions with per-word colors, zoom, cutaway,
and slide all confirmed working — see the sample frames in this handoff).
Alignment (`align.py`) is written but needs a real video + your Whisper model
download to test on your machine (the sandbox this was built in has no
internet access to model repos).

## Pipeline

```
1. align.py   your script.txt + talking_head.mp4  →  words.json
2. plan.py    words.json + broll_manifest.json     →  edl.json   (AI suggests)
3. YOU        open edl.json, tweak times/text/broll picks as needed
4. render.py  talking_head.mp4 + edl.json          →  final.mp4
```

## Setup (on your own machine — this needs your own hardware/internet)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...   # only needed for step 2 (plan.py)
```

The first time you run `align.py`, faster-whisper downloads a model
(~150MB–500MB depending on size). After that it runs fully offline.

## Step-by-step

**1. Write your script as plain text** (see `script.example.txt`), one
sentence per line is fine.

**2. Record your talking-head video** as usual.

**3. Align:**
```bash
python align.py --video talking_head.mp4 --script script.txt --out words.json
```

**4. Tag your b-roll pool** — copy `broll_manifest.example.json`, list your
actual files with a short content tag each (this is what the AI planner
matches against your script content).

**5. Generate the edit plan:**
```bash
python plan.py --words words.json --broll broll_manifest.json --out edl.json
```

**6. Review `edl.json`.** This is plain JSON — open it, read the captions
and beats, fix anything off (wrong b-roll pick, caption grouping you don't
like, a zoom that's too long). This is your approval step.

**7. Render:**
```bash
python render.py --video talking_head.mp4 --edl edl.json --out output/final.mp4
```

## What's in the EDL

- `captions`: phrase-level, with per-word `accent`: `null` | `"gold"` | `"red"`
- `beats`:
  - `zoom_punch` — slow push-in over a time window
  - `cutaway` — full-frame overlay of a b-roll file for a time window
    (talking-head audio keeps playing underneath)
  - `slide` — full-screen big text (auto-generated PNG), for offers/numbers
  - `chord_label` — small text label (e.g. "Am"), rendered as a lightweight
    subtitle style, no separate video overlay needed

## Setup gotcha: you need `ffmpeg-full`, not plain `ffmpeg`

Homebrew's default `ffmpeg` formula on some machines is a minimal build
without libass/freetype — meaning no `subtitles`, `ass`, or `drawtext`
filters, which `render.py` depends on for every caption/slide. If `ffmpeg
-filters` doesn't list `subtitles`, install the full build (it's bottled,
so this is a normal-speed install, not a from-source compile):

```bash
brew install ffmpeg-full   # keg-only, won't touch your regular `ffmpeg`
```

`ffmpeg_util.py` auto-detects a working binary (checks `FFMPEG_BIN` env var,
then the standard `ffmpeg-full` install paths, then whatever `ffmpeg` is on
your `PATH`) so you don't need to change your shell config — just make sure
one of those actually has libass+freetype.

## Status: hardened against real footage (this pass)

`align.py` was validated end-to-end on real (not synthetic) retake-heavy
Indonesian speech and had a real bug fixed as a result: the original
greedy nearest-window fuzzy match could jump to a coincidentally-similar
word much further ahead in the transcript (past an abandoned retake),
silently producing backwards-jumping, garbage timestamps for everything
after that point. It's now a two-pass alignment — global exact-match
anchors via `difflib.SequenceMatcher`, then fuzzy fill strictly bounded
between anchors — which can't make that mistake by construction. See the
docstring on `align_script_to_whisper` in `align.py` for the full story.

Also found during real-footage testing: **use at least `--model-size
medium`** for Indonesian scripts with English loanwords (workshop, chord,
accelerator, etc) — `small` mishears enough of them that there's nothing
close enough left to match against. `medium` is now the default.

## Known v1 limitations / next steps

- **Chord labels** aren't auto-detected from audio — you (or the AI plan
  step) place them manually based on your script mentioning a chord name.
  Real pitch-detection sync (from audio or MIDI) would be a good v2
  addition — nontrivial (needs actual chord/pitch recognition), intentionally
  not attempted in this hardening pass.
- **Zoom** re-evaluates a scale filter every frame, which is fine for
  ad-length clips (<90s) but would be slow on long-form video — not a
  concern for your use case.
- **Fonts**: put a real brand `.ttf` in `fonts/` and point `--font` at it for
  slides; for captions, edit the `font_name` default in `render.py`
  (currently `"Arial Black"`, a real system font on macOS — libass resolves
  it via fontconfig, so this works as long as `ffmpeg-full` was used).
  `render.py`'s slide-text font loader now hard-fails with a clear message
  instead of silently falling back to PIL's tiny bitmap font if no usable
  `.ttf` is found (that used to happen silently — see git history).
- **Multiple videos per batch**: right now each run is one ad. Wrapping this
  in a loop over several scripts/videos is a small addition once you're
  happy with single-ad output quality.
- **`plan.py`'s output isn't validated by a live test in this pass** — no
  `ANTHROPIC_API_KEY` was available in this environment. `validate_edl.py`
  (schema + semantic checks — accent values, caption gap/overlap, beat
  field completeness, b-roll files actually existing in your manifest) is
  wired into both `plan.py` (right after the API call) and `render.py`
  (right before rendering, so a hand-edited `edl.json` gets checked too),
  and was tested against both a valid and a deliberately-broken EDL. Run
  `plan.py` for real once you have a key to confirm the *prompting* still
  produces a schema-valid EDL in practice, not just that the validator
  itself works.

## Files

- `style_bible.md` — the extracted style rules (edit this as your style evolves)
- `align.py`, `plan.py`, `render.py` — the three pipeline stages
- `script.example.txt`, `broll_manifest.example.json` — input format examples
- `test_edl.json` — minimal EDL exercising every beat type (used to validate the renderer)
