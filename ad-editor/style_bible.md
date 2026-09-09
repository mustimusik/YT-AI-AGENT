# Style Bible — extracted from 3 reference ads

Source: 3 IG ad videos (piano/worship course ads), 1080x1920, 30fps, 28–57s.
This file is the ruleset the AI edit-planner is told to follow. Edit it any time
your style evolves — the planner prompt reads this file directly.

## Shot types (in rotation)
- `talking_head` — default resting shot, center-framed, product shelf background
- `broll_hands` — close-up piano hand footage, sometimes warm color-wash tint
- `screen_recording` — falling-notes visualizer, chord label overlay (Am, Dm, G7...)
  synced to the exact moment that chord is played
- `social_proof` — event/crowd photos, holding a physical book to camera
- `slide` — full-screen bold text on plain/blurred bg for a big claim, no talking head
  visible (price reveals, "FREE CLASS", "GRATIS", "LIMITED EDITION")

## Cut pacing
- Cut roughly every 1.5–4 seconds. Never let one shot sit longer than ~5s
  without either a cut, a zoom-punch, or a caption change.
- Hook (first 1–3s) should be the most visually loud shot available
  (crowd footage, bold on-screen claim) — never open on a static talking head.

## Zoom
- At a cut with no b-roll to cut away to (zoom-punch as the pattern
  interrupt itself): SNAP in near-instantly at the cut point (~0.05-0.1s
  ramp, reads as a hard punch, not a glide), then ease slowly back OUT to
  1.0x over the next few seconds of that segment. This is the opposite of a
  continuous push-in — the punch happens at the cut, not gradually building
  toward it. Confirmed against reference footage; a slow build-up read as
  "too abrupt"/mistimed compared to this snap-in-then-release shape.
- A continuous slow push-in ("Ken Burns") is still fine for a segment that
  has NO cut on either end (a long uninterrupted hold) — subtle, ~10-15%
  scale increase over 3-5s, never zooming back out mid-segment in that case.
  But most segments in practice get a cut on at least one side, so the
  snap-in-then-release shape above is the common case.

## Captions
- Bold all-caps sans-serif, white fill, dark stroke/outline, positioned
  vertically centered on the frame (not the bottom third — confirmed against
  reference frames where captions sit at chest height, dead center).
- A caption phrase should never span a sentence boundary (never let one
  phrase end mid-sentence and the next start a new sentence) — break the
  phrase at `.`/`?`/`!` even if that makes the phrase shorter than the
  usual 2-4 words.
- Phrase-level chunks, 2–4 words, tightly synced to speech (no lag).
- Accent 1–2 words per phrase in a different color:
  - Gold/yellow (#FFD400 approx) → feature/benefit keywords
  - Red (#FF2A2A approx) → urgency/scarcity keywords ("GRATIS", "TERBATAS",
    "TAKUT", countdown-style words)
- Numbers/offers get their own oversized standalone treatment, not a normal
  caption: huge central number + smaller line underneath
  (e.g. "99" / "RIBU AJA"), own `slide` beat rather than overlay on face.

## Pattern interrupt inventory (pick 1 per cut, vary — never repeat same
## interrupt type back-to-back)
1. Cut to `broll_hands` (plain or warm-tint)
2. Cut to `social_proof`
3. Zoom-punch on current shot (no cut)
4. Color-flash wash at the cut point (few-frame warm overlay)
5. Cut to `slide` for a claim/number beat
6. Cut to `screen_recording` with chord label pop when explaining technique

## CTA close (last 3-5s of every ad)
- Cut to a `slide` or talking head with down-arrow / shopping-bag icon
- Caption: "KLIK TOMBOL DI BAWAH" style, red/gold accent
- Optional QR overlay with "DENGAN QR VIDEO PENJELASAN" if explaining a bonus

## Fonts / colors (placeholder — replace with real brand assets when available)
- Font: bold condensed sans (e.g. Montserrat ExtraBold / TikTok Sans as stand-in)
- Fill: #FFFFFF, Stroke: #000000 (3-4px at 1080w)
- Accent gold: #FFD400
- Accent red: #FF2A2A
