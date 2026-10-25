# HTML Presentation Template — Specification

**Status:** v1.0 — all round‑1 and round‑2 decisions incorporated; proposal accepted (ready for P0)
**Reference:** `docs/example_presentation_EfficientNet/` (kept untouched as the visual and behavioural baseline)
**Author:** Simon Meier (requirements) · Claude (spec)

---

## 1. Goals and non-goals

### Goals
1. A **reusable presentation template**: one `<prefix>_presentation.html` per talk that opens by double‑click (`file://`) with **no other files, no internet**.
2. **Declarative slide objects.** Slides, steps and animations are declared with HTML and a small config object; no per‑slide JavaScript is needed for normal slides.
3. **Visual parity with the EfficientNet deck:** fonts, sizes, colours, ETH logo, footer, transitions, cover design, buttons, navigator.
4. **Robustness:** missing images, a missing `images/` folder or missing animation files never break the deck. They render as clearly labelled placeholders.
5. **AI‑friendly:** an AI model can create a new presentation by editing only the clearly marked *user zone* of the file, guided by `AUTHORING.md`.
6. **Future‑proof:** the engine is versioned, lives in a marked block, and can be swapped in existing decks by a script.

### Non-goals (for now)
- Speaker notes / presenter view, print/PDF export, resume‑after‑reload (not selected in round 1; the architecture leaves room for them, see §18).
- Editing slides in the browser (WYSIWYG).
- Support for anything other than desktop Chromium (Chrome/Edge) and Firefox.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Deck** | One `<prefix>_presentation.html` file. |
| **Slide** | One `<section>` element in the deck = one slide object. |
| **Step** | A state of a slide. A slide has steps `1…N`; step *k* shows every layer with step ≤ *k* (layers are stacked). |
| **Layer** | An element tagged with `data-step` (and/or `data-step-class`) that appears or changes at a step. |
| **Animation** | A separate `<prefix>_animations.html` file registered in the deck config and shown in an iframe. |
| **Engine** | The generic CSS + JS + vendored fonts/KaTeX that make a deck work. Identical in every deck, versioned. |
| **User zone** | The part of the deck file a user/AI edits: user CSS, `DECK` config, slide sections. |
| **Main zone / Appendix zone** | Slides before / after the black slide. |
| **Canvas** | The fixed logical slide size (e.g. 1280×800) that is scaled uniformly to the window. |
| **Placeholder** | The white, bordered, labelled box shown in place of a missing image or animation. |

---

## 3. Analysis of the EfficientNet deck (what we keep, what we redesign)

### Kept as‑is (behaviour and look)
- Fonts: **Inter** (300–800) for text, **Fira Code** for code. KaTeX for formulas (the original used 0.16.9; the template vendors 0.16.47, R3‑1).
- Design tokens (`--eth #1F407A`, `--ink`, `--muted`, `--fs-*` sizes, `--title-mark`), slide title style, footer style.
- Slide crossfade (`opacity .25s ease`) and layer reveal (`opacity/translateY(6px) .35s ease`).
- Cover slide: aerial background, white "ETH zürich" box top‑left, course info top‑right under the buttons, ETH‑blue title box bottom‑left.
- Top‑right buttons `☰ Slides` and `▶ Animation` (left of Slides), same colours and blur.
- Navigator overlay: blurred backdrop, white panel, list of thumbnail iframes + labels, current slide highlighted.
- Keyboard: → / Space / PageDown / End = forward; ← / PageUp / Home = back (laser‑pointer compatible); Esc closes menus.
- Animation iframes forward navigation keys to the parent via `postMessage`; animations take presets via URL params / `postMessage`.
- Black end slide followed by appendix slides.
- "← → to navigate" hint that fades after 4 s.

### Redesigned
| Problem in the original | Redesign |
|---|---|
| Each stepped slide needs its own counter variable, render function and key‑handler branch (~5 coordinated edits). | One generic **step engine** driven by `data-step` attributes. |
| Slide order (`SLIDES`), footer numbers and navigator metadata (`SLIDE_META`) are maintained by hand and can drift. | Order = document order of `<section>`s; numbers, footers and navigator are **derived**. |
| Steps reset to 0 when leaving a slide forward and jump to the last step when going back. | **Per‑slide step memory** (§8.3). |
| Preview iframes run the full deck, including building their own 20‑iframe navigator. | Dedicated lightweight **preview mode** (§11). |
| Layout is fluid with fixed px sizes, so it looks different on every screen; thumbnails assume 1280×720. | **Fixed logical canvas** scaled to fit (§6). |
| Fonts and KaTeX come from CDNs. | **Vendored inline** (offline). |
| Missing images or animations show broken icons / browser error pages. | **Labelled placeholders** (§10). |
| Animation key presses advance hidden slides while the quick-access overlay is open. | Deck navigation is suspended while an overlay/menu is open (§8.4). |
| Animation button position is hard‑coded (`right:116px`). | Buttons sit in a right‑aligned flex row, so labels of any width fit. |
| Slide‑specific CSS for every slide. | A **component library** distilled from the deck (§14) + a user CSS block. |

---

## 4. Files and folders

### 4.1 A presentation folder (what you present from)
```
MyTalk/
├── MyTalk_presentation.html        ← the deck (stand‑alone, offline)
├── MyTalk_animations.html          ← 0…n animation files, any prefix
├── Extra_animations.html
└── images/
    ├── eth_zurich_aerial.png       ← cover background (copied from template)
    └── …
```
- `<prefix>` is free text chosen by the user. The engine never derives names from it; animation files are referenced by their exact file name in the config.
- The deck only resolves relative paths: `images/<file>` and `<animation file>` next to the deck.

### 4.2 This repository (where the template is developed)
```
CustomPresentations/
├── SPEC.md                         ← this document
├── AUTHORING.md                    ← how to fill a deck (for humans and AI models)
├── CLAUDE.md                       ← short pointer to AUTHORING.md + rules for AI edits
├── engine/                         ← SOURCE OF TRUTH for the engine (edit here, never in decks)
│   ├── deck.css                    ← frame, chrome, navigator, steps, placeholders
│   ├── components.css              ← component library (§14)
│   ├── deck.js                     ← runtime
│   ├── anim-contract.js            ← snippet for animation files (§9.5)
│   ├── VERSION                     ← engine version (semver), stamped into every marker
│   ├── shell/                      ← template skeletons with @@placeholders@@ for the blocks
│   │   ├── presentation.html
│   │   └── animations.html
│   ├── assets/eth_zurich_aerial.png← default cover image (copied to template/images/)
│   └── vendor/                     ← Inter, Fira Code, DM fonts, KaTeX (+auto-render), licences
│       ├── manifest.json           ← pinned packages + files (edit to change versions)
│       └── lock.json               ← generated: url, sha256, size per file
├── tools/
│   ├── fetch_vendor.py             ← downloads manifest files once; --verify checks hashes offline
│   ├── _blocks.py                  ← marker format shared by build/update
│   ├── tests/                      ← unittest suite (python -m unittest discover tools/tests)
│   ├── build.py                    ← assembles template/*.html from engine/ (§16)
│   ├── update.py                   ← replaces the engine block in an existing deck
│   └── new.py                      ← scaffolds a new presentation folder
├── template/
│   ├── template_presentation.html  ← built artefact: copy this to start a talk
│   ├── template_animations.html    ← built artefact: starter animation with the contract
│   └── images/eth_zurich_aerial.png
└── docs/example_presentation_EfficientNet/   ← reference, untouched
```

---

## 5. Deck file anatomy

The deck is one HTML file with two zones, separated by marker comments. The **user zone comes first**, so a person or AI reading the file sees config and slides immediately. The large engine/vendor block is last.

```html
<!DOCTYPE html>
<html lang="en" class="deck-loading">
<head>
  <meta charset="UTF-8">
  <title>EfficientNet — Simon Meier</title>

  <!-- ═════ USER ZONE ═════════════════════════════════════════════ -->
  <style id="deck-user-styles">
    /* presentation-specific CSS; always overrides engine + components */
  </style>
  <script id="deck-config">
    const DECK = { /* §7 */ };
  </script>
</head>
<body>
  <main id="deck">
    <section data-type="title"></section>
    <section data-type="toc"></section>
    <section data-type="content"> … </section>
    …
    <section data-type="black"></section>
    <section data-type="content"> … </section>   <!-- appendix -->
  </main>
  <!-- ═════ END USER ZONE ═════════════════════════════════════════ -->

  <!-- DECK-ENGINE:BEGIN v1.0.0 | generated by tools/build.py - do not edit -->
  <style id="deck-engine-css"> @layer engine, components; … </style>
  <style id="deck-vendor-css"> @font-face{…base64…} /* KaTeX CSS + fonts */ </style>
  <script id="deck-vendor-js"> /* katex.min.js + auto-render */ </script>
  <script id="deck-engine-js"> /* deck.js */ </script>
  <!-- DECK-ENGINE:END -->
</body>
</html>
```

Rules:
- **Marker format** (stable contract, `tools/_blocks.py`): `<!-- NAME:BEGIN v<semver> | generated by tools/build.py - do not edit -->` … `<!-- NAME:END -->`, plain ASCII, each name exactly once per file. Deck files have `DECK-ENGINE` (end of `<body>`). Animation files have `ANIM-VENDOR` (fonts + KaTeX, in `<head>` so they load before the animation's own scripts) and `ANIM-CONTRACT` (end of `<body>`).
- **CSS precedence:** engine CSS is in `@layer engine`, the component library in `@layer components`, user CSS is unlayered. User CSS therefore always wins, regardless of document order.
- **No flash of unstyled content:** `<html class="deck-loading">` hides `#deck` until the engine has initialised.
- **AI‑safety:** base64 blobs are written as single long lines inside the engine block. `AUTHORING.md` tells AI models never to read or edit past the `ENGINE` marker.

---

## 6. Canvas and scaling

- All slide content is laid out on a **fixed logical canvas** `DECK.canvas = { width, height }` in CSS px.
- The canvas is scaled uniformly with `transform: scale(s)`, `s = min(innerWidth/width, innerHeight/height)`, centred, and recomputed on `resize`.
- Everything lives inside the canvas: slides, footer, top buttons, navigator, animation picker and animation overlay. This keeps one stacking context and makes thumbnails exact miniatures.
- **Letterbox bars** (when the screen ratio differs) take the **background colour of the current slide** (white, black, cover blue `#1c2f52`, animation beige `#f5f3ee`), so they are nearly invisible.
- Iframes inside the canvas (animations) see a viewport of the canvas size and are scaled with it.
- **Default canvas: 1280×800 (16:10)** (decision R2‑1). Measured setup: laptop 2560×1600 @225% ⇒ browser viewport ≈ 1138×711 (16:10); second screen 1920×1200 @150% = 1280×800. The original px values were tuned to the ~711 px laptop height, so **every engine/component px value is the original × 1.125** (rounded to 0.5 px). Text and spacing therefore look exactly as large as in the EfficientNet deck on the laptop.
- `DECK.canvas` can be changed per deck (e.g. `{1280, 720}` for a 16:9 beamer). The scale‑factor rule only applies to the default; tokens are not re‑derived automatically.

---

## 7. The `DECK` config

```js
const DECK = {
  // ── Cover ─────────────────────────────────────────────
  title:     'EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks',
  subtitle:  'Mingxing Tan, Quoc V. Le (2019)',      // optional; line below the title
  presenter: 'Simon Meier',                          // default 'Simon Meier'
  course: {
    title:    '252-4811-00L Machine Learning',
    type:     'Seminar',
    semester: 'FS26',
  },
  cover: {
    background:  'images/eth_zurich_aerial.png',     // default
    boxMaxWidth: '58%',                              // cap for the blue box (§12.1)
  },

  // ── Table of contents (slide 2) ───────────────────────
  toc: [
    'Motivation',
    { text: 'Method', sub: ['Observations', 'Compound scaling'] },
    'Results',
    'Outlook',
  ],

  // ── Animations (global, fixed order = picker order) ───
  animations: [
    { id: 'scaling', name: 'Model Scaling', file: 'EfficientNet_animations.html' },
  ],

  // ── Misc ──────────────────────────────────────────────
  date:   'auto',                       // 'auto' = today (DD.MM.YYYY), or a fixed string
  canvas: { width: 1280, height: 800 }, // 16:10 default (§6)
  hooks:  {},                           // optional per-slide JS (§8.5)
};
```

Validation: the engine checks the config at start‑up. Problems (unknown animation id, missing title, invalid step attributes, formula errors, etc.) are always logged with `console.warn` and collected in `Deck.warnings`. The red "deck warnings" badge (bottom‑left, expandable list, dismissible) is shown **only when the deck is opened with `?dev`** in the URL (decision R4‑1); in dev mode a green "✓ no deck warnings" badge confirms a clean deck. In addition, dev mode shows every problem inside the **☰ Slides navigator** and turns its button red (§12.6). The live talk and preview mode never show either.

---

## 8. Slides and steps

### 8.1 Slide types
Each slide is a `<section>` inside `<main id="deck">`. Order in the file = order in the presentation.

| `data-type` | Required position | Rendered by | Default chrome | Numbering |
|---|---|---|---|---|
| `title` | first | engine, from `DECK` | logo top‑left, course info, buttons; **no** footer/default styling | 1 (not displayed) |
| `toc` | second | engine, from `DECK.toc` (title "Table of Contents") | standard | 2 |
| `content` | anywhere after `toc` | author HTML | standard | 3, 4, … / Appendix 1, 2, … |
| `animation` | anywhere after `toc` | engine, iframe of a registered animation | footer over iframe | numbered like content |
| `black` | exactly one, after the main slides | engine | **only** the top buttons | none ("–" in navigator) |

- Slides after the `black` slide form the **appendix zone**. They are numbered **"Appendix 1", "Appendix 2", …** in both the footer and the navigator. Both `content` and `animation` slides are allowed there.
- Optional `id="…"` on any section gives a stable name for hooks and debugging; otherwise the engine assigns `slide-<n>`.
- Position violations (e.g. two `title` slides, missing `black`) produce a deck warning but still render.

### 8.2 Content slide markup
```html
<section data-type="content">
  <h2 class="slide-title">Observation 1 – scaling <span class="title-mark"><em>any</em> single dimension</span> improves accuracy</h2>

  <div class="figure">
    <img src="images/folie10_graphs.png" width="1600" height="720" alt="…">
    <div class="overlay-line" style="top:16%" data-step="2"></div>
    <div class="overlay-label" style="top:9%" data-step="2">~80% accuracy ceiling</div>
  </div>
</section>
```
- The engine wraps the author's children into the standard frame: `.slide-content` (padding `38px 56px 72px`, flex column) + footer (ETH logo bottom‑left; date + number bottom‑right).
- The **slide title** is the first `.slide-title` element (HTML allowed). The navigator uses its text content. If a slide has no visible title, `data-title="…"` supplies the navigator label.
- Per‑slide background: `data-bg-color="#f5f3ee"` (also drives the letterbox colour).
- Opt‑out of the default frame padding: `data-layout="full"` (content gets the whole canvas; footer stays).

### 8.3 Step model
- Every slide has `N ≥ 1` steps. `N` = the highest step number referenced inside the slide, or the value of `data-steps="N"` on the section (needed when only a hook uses the steps).
- **Step 1 shows only the slide title** (decision R5‑1). Steps are cumulative: step *k* shows everything whose range contains *k*; a range can also remove an element again (`data-step="1..2"` disappears at step 3).
- The slide title (`.slide-title`) is always visible. **Unmarked content appears at step 2.** Precisely: inside the content frame, every element without `data-step` that contains no stepped descendant becomes an implicit `data-step="2"` layer (marked `data-step-implicit`). An unmarked element that *does* contain stepped descendants stays a structural container and the rule continues inside it. So `data-step="1"` anywhere means "visible from the start", e.g. in `<ul><li>A</li><li data-step="1">B</li><li data-step="3">C</li></ul>` B shows at step 1, A at 2, C at 3.
- The rule applies to `content` and `toc` slides (the generated TOC list appears at step 2), not to `title`, `black` or `animation` slides.
- **Visibility attribute `data-step`:**

  | Value | Visible when current step *s* … |
  |---|---|
  | `"3"` | *s* ≥ 3 (layer stays once revealed — the default) |
  | `"2..4"` | 2 ≤ *s* ≤ 4 |
  | `"3..3"` | only at *s* = 3 |

- **Class attribute `data-step-class`** (for highlights that do not hide/show), space‑separated rules `class:range`:
  `data-step-class="hi:3..3 hl-conv:2"` → `.hi` only at step 3, `.hl-conv` from step 2 on.
  This covers the original's "Problem – **Insight** – Method – Result" title highlight and the code underline glows.
- **Effects** `data-step-fx="rise|fade|slide-left|none"` (default `rise` = `opacity 0→1, translateY(6px)→0, .35s ease`; `slide-left` = original resolution panels `translateX(-12px), .4s`). Hidden layers keep their space (opacity only), so the layout never jumps, as in the original.
- **Arrival rule:** the first time a slide is entered **forward** it shows step 1; entering an unvisited slide **backward** shows step N (final). Example (original slide 3, rebuilt): title at step 1, Problem unmarked (step 2), Insight `data-step="3"`, Method `"4"`, Result `"5"`. To show Problem on arrival as in the original, mark it `data-step="1"`.

### 8.4 Navigation state machine
State: `current` slide index, `steps[i]` (current step of slide *i*), `visited[i]`.

| Input | Behaviour |
|---|---|
| forward (→ ↓ Space PageDown End) | if `steps[cur] < N` → `steps[cur]++`; else go to slide `cur+1` (if any) |
| back (← ↑ PageUp Home) | if `steps[cur] > 1` → `steps[cur]--`; else go to slide `cur-1` (if any) |
| enter slide *i* (forward / back / navigator jump) | if `visited[i]` → **restore `steps[i]`**; else step 1 (forward, jump) or N (back); mark visited |
| Esc | close navigator or picker (never closes an animation overlay; animations may use Esc) |

- While the **navigator, the animation picker, or an animation overlay** is open, forward/back are ignored by the deck. Key messages forwarded from the overlay's iframe are dropped, so slides don't change invisibly behind the animation.
- On an **animation slide**, the embedded iframe forwards navigation keys, so → / ← move between slides even when the iframe has focus (same as the original).
- When an overlay closes, the engine moves focus back to the deck (`window.focus()`), so keys work immediately.
- Step changes and slide changes are instant state updates; visuals animate via CSS transitions only (rapid key presses stay consistent).

### 8.5 Hooks (escape hatch for custom behaviour)
```js
hooks: {
  'timeline': (step, slideEl, ctx) => { /* e.g. measure label widths */ },
}
```
Called with the slide's `id` after every render of that slide (arrival, step change, preview render). `ctx = { preview: bool, first: bool, N }`. Hooks must be idempotent (the same step may be rendered repeatedly).

---

## 9. Animations

### 9.1 Registry
`DECK.animations` is the **single, ordered list** of animations: `{ id, name, file }`. Its order is the fixed global order used everywhere (picker, warnings).

### 9.2 The animation button
Placed directly left of `☰ Slides`, same style. Visibility depends on the number of registered animations, **not** on whether the files exist:

| # registered | Button | Behaviour |
|---|---|---|
| 0 | hidden | — |
| 1 | `▶ Animation` ↔ `◀ Presentation` | Exactly as in the original: toggles a full‑canvas overlay with an independent, persistent instance of the animation (state survives closing/reopening). |
| ≥ 2 | `▶ Animations` while the slides are shown, `⇄ Switch` while an animation is open | Every click opens the **animation picker**. |

### 9.3 Animation picker (≥ 2 animations)
- Same overlay/panel design as the slides navigator, heading "Animations".
- Entries in fixed order: **1. Presentation** (thumbnail = title‑slide preview), then **every animation in `DECK.animations` order** (thumbnail = live iframe of the animation file + its `name`).
- The entry for what is currently shown (presentation or animation X) is highlighted.
- Choosing an animation shows its overlay instance (one persistent instance per animation, created on first use, so state survives switching). Choosing *Presentation* closes any overlay.
- Missing animation files show their placeholder as thumbnail and as overlay (§10).

### 9.4 Animation slides
```html
<section data-type="animation" data-anim="scaling"
         data-params="open=compound,resnet&mode=discrete&phi=1&rn_version=4"
         data-title="ResNet-152 vs EfficientNet-B1"></section>
```
- Renders an iframe `file?deck-embed=1&<params>` filling the canvas, with the footer on top (as original slides 4, 9, 11, 13, 14). Background `#f5f3ee` unless `data-bg-color` is set.
- Every animation slide has **its own independent instance** (state preserved when navigating away and back), separate from the overlay instance(s).
- Animation slides have one step; arrow keys move to the next/previous slide.
- `data-title` is required (navigator label; not displayed on the slide).

### 9.5 Animation contract (protocol v1)
Every animation file must contain the standard **contract snippet** (`engine/anim-contract.js`, pre‑installed in `template_animations.html`, between `ANIM-CONTRACT` markers so `tools/update` can refresh it).

All messages are objects `{ ns: 'deck', v: 1, type, … }` sent with `postMessage(msg, '*')`. `file://` pages have opaque origins, so identity is checked via `event.source === iframe.contentWindow`, not via origin.

| Direction | `type` | Payload | When |
|---|---|---|---|
| anim → deck | `ready` | `{ name? }` | on `DOMContentLoaded`, and in reply to `ping` |
| deck → anim | `ping` | – | after iframe `load`, as a race-free backup |
| anim → deck | `key` | `{ key }` | navigation keys (→ ← Space PageUp PageDown Home End) pressed inside the animation |
| deck → anim | `preset` | `{ preset: {...} }` | optional runtime preset (animation calls `window.applyPreset(preset)` if defined) |

- URL parameters: the deck passes `deck-embed=1` (and `deck-thumb=1` for picker thumbnails) plus the slide's `data-params`. Interpreting params is the animation's job (the EfficientNet `readURLParams`/`applyPreset` pattern is the recommended model and lives in the template).
- **Missing detection:** if no `ready` arrives within **1500 ms after the iframe's `load` event** (or 4000 ms total), the iframe is replaced by the animation placeholder.
- Legacy compatibility: the deck also accepts the original `{type:'keydown', key}` message. The original `{type:'applyPreset'}` is not needed. An animation **without** the snippet is treated as missing (decision R1‑4). Porting the EfficientNet animation means adding the ~15‑line snippet.

---

## 10. Assets and placeholders

### 10.1 Placeholder look (decisions R1‑4, R2‑5, R7‑2)
A white box with a **border** (2px `#c9c9c9`), **exactly the size the asset would occupy**, with a centred grey one‑line label:
- `image "folie8_dogs.png" not found`
- `animation "EfficientNet_animations.html" not found`

The label uses the **file name only** (no folder). It **scales with the box** (about 80 % of its width, at most a third of its height), so large placeholders get a large label and small ones a small label. For images the placeholder is an SVG generated by the engine (system sans‑serif font: an SVG used as an image cannot use the deck's fonts; a desaturation filter keeps the label grey at small sizes).

### 10.2 Images (`<img>`) — implemented
- Authoring rule: every `<img src="images/…">` carries **`width` and `height` attributes with the image's natural pixel size**. A missing attribute pair is **always** a deck warning, even when the file loads (decision R7‑1); the P6 tooling can fill them automatically.
- The engine CSS sets `#deck img { width:auto; height:auto; max-width:100% }`: the attributes then only provide the intrinsic size and aspect ratio, and any CSS width *or* height scales the image proportionally (without this, the `height` attribute would stay fixed when CSS changes only the width).
- On a load error (also one that happened before the engine started: `complete && !naturalWidth`) the **`<img>` element is kept** and its `src` is swapped for the placeholder SVG of `width × height`. All CSS rules (including tag selectors like `.figure img`), `id`, `class` and step attributes keep working, so the placeholder sits exactly where and how large the image would be. The element gets `data-asset-missing="<original src>"` and `.asset-missing`.
- **Remembered sizes** (decision R7‑3): whenever an image loads, its natural size is stored in the browser's `localStorage` (key `deck-image-sizes:<deck path>`, map `src → [w, h]`). A missing image **without** width/height attributes uses the remembered size; only if there is none, it falls back to the parent's width at 16:9. This works per computer/browser; the attributes in the file remain the robust solution. Placeholder sizes are never stored.
- A missing `images/` folder is just "every image missing"; nothing special is needed.
- Every missing image is a deck warning attributed to its slide and to the first step at which it is visible (shown in the dev navigator).

### 10.3 Background images (`data-bg`) — implemented
- CSS `url(images/…)` cannot be checked for existence, so image backgrounds are declared via `data-bg="images/x.png"`. Defaults: `background-size: cover; background-position: center; no-repeat`; optional `data-bg-size` / `data-bg-position` override them (e.g. sprite usage like the original resolution strip).
- The engine preloads each with `new Image()`. On success it sets `background-image`; on failure the element gets the placeholder (stretched to the element's own box) and a warning.
- In `?dev`, `url(...)` image references in the user CSS or in inline `style` attributes are reported (use `<img>` or `data-bg` instead).
- **Cover:** `DECK.cover.background` is loaded the same way. If it is missing, the whole cover becomes the placeholder (slide background and letterbox turn white) and the course info text switches from white to `--ink` so it stays readable. The blue title box stays.

### 10.4 Animations
The iframe is replaced by a placeholder of the same box (full canvas on animation slides and overlays; thumbnail size in the picker).

---

## 11. Preview mode (thumbnails)

- **Implemented** (used by the navigator thumbnails). URL: `<deck>.html?preview=<index or slide id>[&step=<k>]` (default *k* = final step N, i.e. "show the final step of all slides").
- In preview mode the engine renders **only** that slide and hides the top buttons, hint, warnings badge, navigator and picker. It builds **no** thumbnails (no recursion), registers no keyboard handling, and still loads animation iframes on animation slides so their preview is real.
- Thumbnails are iframes at canvas size, scaled into a box of width 112 px (height by canvas ratio).
- **Loading strategy:** at start‑up the navigator list and all thumbnail iframes are created **one after another** (next starts when the previous fires `load`). They stay alive for the session, so opening the navigator is instant and the presentation's first slide is never slowed down.

---

## 12. Slide chrome and special slides

### 12.1 Title slide
- Full‑bleed background `DECK.cover.background` (`center/cover`, base colour `#1c2f52`).
- Top‑left: white box "**ETH** zürich" (`20px`, weight 900/400, as original).
- Top‑right, below the buttons (`top:62px; right:16px`): `course.title` ⏎ `course.type, course.semester` (white, 13px, text‑shadow).
- **Blue box** (`--eth`), anchored `left:0; bottom:28px`, padding `40px 52px 44px 44px`, containing title (`--fs-cover-title`, 700), subtitle (`--fs-sub`, 78% white; omitted if empty), presenter (`--fs-body`, 700).
  - **Size to content:** `width: max-content; max-width: DECK.cover.boxMaxWidth (58%)`; height `auto`. A short title gives a narrow box, a long one wraps inside the cap. `text-wrap: balance` on the title gives even line lengths. The box grows only as tall as title + subtitle + presenter need.
  - **Implemented by measurement:** CSS `max-content` alone keeps the full max‑width as soon as the title wraps, so after layout (and again when fonts are ready) the engine measures the longest rendered line of title, subtitle and presenter (`Range.getClientRects()`) and sets the box width to that line plus padding. Result: the box is exactly as wide as its widest line, never wider than `boxMaxWidth`.
  - Content written into the title `<section>` is ignored (deck warning); the cover is always rendered from `DECK`.
- No footer, no slide title, no default padding. The top buttons are present.

### 12.2 Table of contents slide
Standard frame, title "Table of Contents", bullets from `DECK.toc` (strings or `{text, sub:[…]}` for one nested level): ETH‑blue numbered circles (as on the original Motivation slide) at `--fs-body`, sub‑items as `–` dashes at `--fs-sub` (decision R4‑3). TOC text may contain `$…$` math. Like every slide, step 1 shows only the title; the whole list appears at step 2 (R5‑1). (Authors who want a different reveal can write the TOC section's content themselves; the engine then leaves it alone.)

### 12.3 Black slide
Pure `#000`, letterbox black. Only the top buttons are visible. Navigator label "–" / "End".

### 12.4 Footer and numbering
- Bottom‑left: "**ETH** zürich" (13px). Bottom‑right: date and number as two spans with a 1em gap, e.g. `01.02.2026   3` (13px, `--muted`; decision R4‑2).
- Numbering: title = 1, TOC = 2, then sequential through `content`/`animation` slides; black slide none; appendix "Appendix 1…".
- Date: `DECK.date === 'auto'` → today's local date, refreshed automatically at midnight. Otherwise the fixed string is used.

### 12.5 Top buttons
A fixed right‑aligned flex row (`top:16px; right:16px; gap:8px`) inside the canvas: `[▶ Animation] [☰ Slides]` (implemented; the animation button follows in P4). Styling as original (`rgba(31,64,122,.88)`, white, 13px, 600, radius 8px, blur). Present on **every** slide (title and black included), above overlays (z‑index), hidden only in preview mode.
- The "← → to navigate" hint sits bottom‑centre inside the canvas and fades out after 4 s (not in preview mode).

### 12.6 Slides navigator
- Opens/closes via `☰ Slides`, click on the backdrop, or Esc.
- Panel "All Slides", one row per slide: thumbnail (§11), number line (`Slide 7` / `Appendix 1` / `–`) and title (slide title text). The subtitle line from the original is dropped (decision: number + title only).
- The current slide is highlighted and scrolled into view on open. Clicking a row jumps there (step memory rules apply) and closes the panel.

- **Implemented.** Thumbnails for all slides are created right after start‑up and load one after another; they stay alive for the session.
- **Dev mode (`?dev`) — the navigator doubles as the problem list** (decisions R6‑1…R6‑4):
  - the ☰ Slides button is red while the deck has problems (ETH blue when clean); without `?dev` it never changes;
  - a red **Deck** box above the list shows problems that belong to no single slide (configuration, structure);
  - every slide row with problems gets a red border and lists its problems, each prefixed with the **step at which it becomes visible** (`step 3 · formula error …`), sorted by step;
  - clicking a row with problems jumps to the **first step that shows a problem**; clicking a clean row uses step memory (as without `?dev`);
  - the step of a problem is derived from its element (the latest start of the step layers around it), from the step a hook threw at, or is 1 for slide‑level problems. `Deck.problems` exposes `{ message, slide, step }`.
  - the bottom‑left badge (§7) stays as a summary.

### 12.7 (removed)
The separate ⚡ dev panel from the P1 follow‑up was replaced by the dev mode of the navigator (§12.6, decision R6‑1), so there is only one slide list to maintain.

---

## 13. Typography, colours, math

- Tokens (original value × 1.125 for the 1280×800 canvas, §6):

  | Token | Original | Canvas value |
  |---|---|---|
  | `--fs-cover-title` | 48px | 54px |
  | `--fs-title` | 36px | 40.5px |
  | `--fs-body` | 24px | 27px |
  | `--fs-sub` | 22px | 25px |
  | `--fs-code` | 20px | 22.5px |
  | `--fs-math` | 32px | 36px |
  | `--fs-footnote` | 13px | 14.5px |

  All other px values quoted elsewhere in this spec (paddings, button sizes, 28px box offset, etc.) are **original** values and are multiplied by 1.125 in the engine CSS in the same way.

  `--eth #1F407A · --ink #1a1a1a · --muted #666 · --title-mark #8B6FC4` + a neutral accent palette `--accent-1…4` (the original `--dep/--wid/--res` green/blue/orange become `--accent-1/2/3`; papers can alias them in user CSS).
- **Math:** KaTeX 0.16.47 + auto‑render, run once over all slides at start‑up (before thumbnails render). Delimiters: `$…$`, `\(…\)` inline; `$$…$$`, `\[…\]` display (display size `--fs-math`). A literal dollar sign is written `\$` (auto‑render does not support this natively; the engine pre‑processes it in P5). Render errors are shown in red inline (`throwOnError:false`); every formula is additionally parsed strictly (via auto-render's `preProcess`), and one that parses in neither inline nor display mode is reported as a deck warning.
- Fonts and KaTeX (CSS, JS, fonts) are inlined as base64 in the engine block. Licences (OFL / MIT) are kept in `engine/vendor/`.

---

## 14. Component library (from the EfficientNet deck)

All components live in `@layer components`, use the design tokens, and work with `data-step`. Each gets a copy‑paste snippet in `AUTHORING.md`.

| Component | Class(es) | Origin in EfficientNet deck |
|---|---|---|
| Numbered list | `.num-list > .num-item` (`.num`, `.num-sub`) | Motivation bullets |
| Label + description rows | `.ld-list > .ld-row` (`.label`, `.desc` with left rule) | Problem/Insight/Method/Result, Transfer‑learning options |
| Stepped title words | `.step-title` + `data-step-class="hi:k..k"` | PIMR title highlight |
| Code block | `.code-block` with tokens `.ck .cf .ca .cn`, highlights `.hl-orange`, `.hl-teal` | Conv2d code line |
| Formula / highlight box | `.formula-box` (orange left border) | Compound scaling formula |
| Info box | `.info-box` (grey, inner list) | "FLOPS scale differently" |
| Conclusion box | `.conclusion-box` (red left border) | "Each ϕ step → FLOPS × 2^ϕ" |
| Takeaway sections | `.takeaways > .tk-section > .tk-header + .tk-sub*` (optional `.borderless`) | Key takeaways, Outlook |
| Figure with overlays | `.figure` + `.overlay-line`, `.overlay-label` (positioned in %) | Observation 1 red ceiling line |
| Image strip / sprite panels | `.image-strip > .strip-panel` (+ `data-bg` sprite helpers) | Resolution dog panels |
| Timeline | `.timeline > .tl-event` (`style="left:%"`, `.tl-year`, `.tl-name`, `.tl-sub`, image) | CNN arms race |
| Data table | `.data-table` (`.row-group`, `.row-hl`, `.row-marker`, `.col-sep`) + `.table-note` | Results tables |
| Two columns | `.cols` (`.col`, `.col-fixed`) | Transfer learning + logo |
| Centred stage | `data-layout="center"` | Formula slide |
| Punchline | `.punchline` | "EfficientNet is Gordon Ramsay" |
| Accent text | `.title-mark`, `.accent-1…4` | Title marks, d/w/r colouring |

---

## 15. Animation template (`template_animations.html`)

- Stand‑alone page with the **contract snippet** (§9.5), its own vendored fonts/KaTeX (offline), the preset pattern (`readURLParams()` + `applyPreset(cfg)`), and one small demo animation that shows how panels/presets work.
- Look: **EfficientNet animation style** (DM Sans / DM Serif Display / DM Mono, beige `#f5f3ee` background, paper panels, sidebar cards), with those fonts vendored inline (decision R2‑3).
- Works on its own (opened directly) and embedded (`deck-embed=1`).

---

## 16. Tooling

| Tool | Purpose |
|---|---|
| `tools/build.py` | Reads `engine/*` + vendor files, writes `template/template_presentation.html` and `template/template_animations.html` with the engine and contract blocks inlined between markers, stamped with the engine version. |
| `tools/update.py <deck.html>` | Replaces the `ENGINE` block (and in animation files the `ANIM-CONTRACT` block) with the current template's version. Writes a `.bak`, prints the old → new version, never touches the user zone. Refuses if markers are missing or duplicated. |
| `tools/new.py <folder> <prefix> [--anim <animprefix>]` | Copies the template into a new folder, renames files to `<prefix>_presentation.html` / `<animprefix>_animations.html`, copies `images/eth_zurich_aerial.png`. |
| (later) `tools/lint.py <deck.html>` | Static checks: image size attributes, unknown animation ids, step gaps, slide order, missing titles. Could auto‑fill `width`/`height` from the images folder. |

Implementation language: **Python 3, standard library only** (decision R2‑4), e.g. `python tools/update.py MyTalk/MyTalk_presentation.html`. Engine versioning: semver in the marker. A deck built with engine 1.x must keep working with any 1.y (attribute/config names are the public API).

---

## 17. Proposed implementation (architecture of `deck.js`)

```
boot()
 ├─ readConfig()            DECK + defaults, validate → warnings[]
 ├─ mode = ?preview ? 'preview' : 'present'
 ├─ buildCanvas()           #stage wrapper, scale on resize, letterbox colour
 ├─ parseSlides()           <section>s → Slide objects {el, type, id, index, zone, number, label, N}
 │                          (renders title / toc / black / animation slides, wraps content frame,
 │                           computes N from data-step / data-step-class / data-steps)
 ├─ renderMath()            KaTeX auto-render over #deck
 ├─ assets.init()           img error capture, data-bg preloading, placeholders
 ├─ anims.init()            message router (ready/key), iframe factory with timeout → placeholder
 ├─ if preview: show(index, step ?? N); done
 ├─ chrome.init()           footer numbers + date timer, top buttons, hint
 ├─ navigator.init()        list + staggered thumbnail iframes
 ├─ picker.init()           (≥2 animations) list + thumbnails; overlay instances on demand
 ├─ input.init()            keyboard + forwarded keys → nav.forward()/back(), Esc
 └─ nav.show(0)             remove .deck-loading
```

- **Slide rendering = pure function of state:** `renderSlide(slide, step)` toggles `.is-shown` on layers and classes from `data-step-class`, then calls the hook. The same function serves presentation, back‑navigation and preview, so there is no special-case code per slide.
- **Public debugging API:** `window.Deck = { goTo(i, step?), next(), prev(), state, slides }`.
- **Zero dependencies** beyond vendored KaTeX; plain ES2020, no build step needed to *run* a deck.

---

## 18. Implementation path

Each phase ends with something demonstrable. Acceptance criteria are checked in Chrome/Edge (primary) and Firefox, opened via `file://`.

| Phase | Content | Acceptance criteria |
|---|---|---|
| **P0 Setup** ✅ done | Repo layout (§4.2), `engine/` skeleton, fetch + commit vendor files (KaTeX 0.16.47, Inter, Fira Code, DM fonts) and licences, `tools/build.py`, tests. | Vendor files hash‑locked; build produces both templates (smoke‑test content only); verified offline in headless Edge (no network, all fonts + KaTeX render). |
| **P1 Core engine** ✅ done | Canvas scaling + letterbox, slide parsing, content frame, footer/numbering/date, crossfade, keyboard, **step engine + step memory**, hooks, warnings badge. | A test deck with 5 stepped content slides behaves per §8.3/§8.4; numbers/dates correct; resizing keeps layout identical. |
| **P2 Special slides + navigator** ✅ done | Title slide (measured shrink‑to‑fit box), ☰ Slides button + navigator with live thumbnails, dev problems inside the navigator, hint. Earlier: TOC, black slide, appendix numbering, top‑button row, overlay component, preview mode. | Cover matches the original visually; box shrinks/grows with title length; navigator shows final steps; previews do not recurse. |
| **P3 Assets** ✅ done | `img` error handling, `data-bg`, placeholders, cover fallback. | Deleting `images/` shows correctly sized, labelled placeholders everywhere; no console errors other than the expected 404s. |
| **P4 Animations** | Contract snippet, animation slides, 1‑animation toggle, picker for ≥ 2, persistent instances, missing‑file placeholders, key suppression while an overlay is open. | Scenarios with 0 / 1 / 3 animations (one missing) behave per §9; state persists across open/close and slide changes. |
| **P5 Look & components** | KaTeX auto‑render, inlined fonts, component library (§14), parity pass against the original. | Side‑by‑side screenshots of rebuilt EfficientNet slides match the original; works with Wi‑Fi off. |
| **P6 Template + tooling + docs** | `template_presentation.html` (title, TOC, **3 empty content slides**, black slide, 1 appendix example), `template_animations.html`, `tools/build/update/new`, `AUTHORING.md`, `CLAUDE.md`. | `tools/new` → working deck in < 1 min; `tools/update` upgrades a deck without touching the user zone. |
| **P7 Validation port** | Port the EfficientNet deck + animation to the template as `examples/EfficientNet/`. | All 20 original slides reproduced with no per‑slide JS except the timeline hook. |

---

## 19. Open questions

None. All questions from rounds 1 and 2 are resolved (§20). New questions that come up during implementation are added here and resolved before the phase that depends on them.

---

## 20. Decision log

| # | Decision | Source |
|---|---|---|
| R1‑1 | Fully offline: fonts + KaTeX inlined into the engine block. | Round 1 |
| R1‑2 | Fixed canvas scaled to fit (size: R2‑1); configurable via `DECK.canvas`. | Round 1 + measurement |
| R1‑3 | Authoring = `<section>` slides with data attributes + one `DECK` config object. | Round 1 |
| R1‑4 | Step memory: always restore a visited slide's saved step; unvisited forward → step 1, backward → final. | Round 1 |
| R1‑5 | ≥ 2 animations: button always opens the picker; picker order = Presentation, then fixed global animation order. | Round 1 |
| R1‑6 | Ship a component library distilled from the EfficientNet deck. | Round 1 |
| R1‑7 | Extras in scope: engine update script only (no notes/presenter view/PDF/resume). | Round 1 |
| R1‑8 | Animations must include the standard contract snippet (handshake + key forwarding + presets); no snippet ⇒ treated as missing. | Round 1 |
| R1‑9 | Missing image/animation ⇒ white bordered box at the asset's normal size with `image "…" not found` / `animation "…" not found`. | Round 1 |
| R3‑1 | KaTeX 0.16.47 (latest 0.16.x patch) instead of 0.16.9. | Round 3 |
| R3‑2 | Git repository on `main`, no remote; vendor files committed. | Round 3 |
| R4‑1 | Warnings badge only with `?dev` in the URL; otherwise console only. | Round 4 |
| R4‑2 | Footer: date and number as separate spans with a ~1em gap. | Round 4 |
| R4‑3 | TOC uses ETH‑blue numbered circles, sub‑items with dashes. | Round 4 |
| R4‑4 | ↓/↑ added as forward/back keys; no click navigation, no number+Enter jump. | Round 4 |
| D‑7 | CSS layers: `reset < vendor < engine < components < user`. The reset sits below vendor so it never overrides KaTeX spacing. Animation files keep vendor CSS unlayered. | P1 |
| D‑8 | Plain text inside `.slide-content` defaults to `--fs-body` / line‑height 1.5. | P1 |
| D‑9 | Engine tests run fixture decks in headless Edge/Chrome via `file://` with network disabled (`tools/tests/browser.py`); skipped if no browser is installed. | P1 |
| R5‑1 | Step 1 = slide title only; unmarked content appears at step 2; `data-step="1"` puts content into step 1; containers with stepped descendants stay structural. Applies to content and TOC slides. | Round 5 |
| ~~R5‑2~~ | ~~⚡ panel lists all warnings, grouped per slide (plus a Deck row), with preview iframe and jump.~~ Superseded by R6‑1/R6‑2. | Round 5 |
| R5‑3 | The bottom‑left warnings badge stays (now alongside the dev navigator). | Round 5 |
| ~~R5‑4~~ | ~~⚡ is leftmost in the top‑right row, symbol only, `?dev` only; clicking a row jumps to the slide's final step.~~ Superseded by R6‑1/R6‑4. | Round 5 |
| R6‑1 | No separate ⚡ panel: ☰ Slides is the only navigator; `?dev` adds the problem information to it. | Round 6 |
| R6‑2 | Deck‑wide problems in a red "Deck" box above the slide list (dev only, only when present). | Round 6 |
| R6‑3 | In `?dev` the ☰ Slides button is red when there are problems; no "problems only" filter. | Round 6 |
| R6‑4 | Row click: normal → step memory; `?dev` + problems → first step at which a problem is visible; `?dev` + clean → step memory. | Round 6 |
| D‑10 | Cover box width is measured after layout/fonts (longest rendered line + padding); title uses `text-wrap: balance`. | P2 |
| R7‑1 | `<img>` without width/height attributes is always a deck warning. | Round 7 |
| R7‑2 | Placeholder label scales with the box. | Round 7 |
| R7‑3 | Natural image sizes are remembered in `localStorage` per deck file and used for missing images without size attributes (a page cannot write into its own .html; the permanent fix is the P6 tool that writes the attributes). | Round 7 |
| D‑11 | Missing images keep their `<img>` element (src swapped for an SVG placeholder) instead of being replaced by a `<div>`, so CSS and step attributes keep applying. `#deck img { width:auto; height:auto; max-width:100% }`. | P3 |
| D‑5 | Vendor sources: jsDelivr (`katex`, `@fontsource(-variable)/*` 5.3.0), subsets latin, latin‑ext, greek(+ext); Inter as variable font (100–900). | P0 |
| D‑6 | Engine version stays 0.x during P0–P5 and becomes 1.0.0 at the end of P6. | P0 |
| R2‑1 | Canvas 1280×800 (16:10); all original px values × 1.125. | Round 2 |
| R2‑2 | ≥ 2 animations: button label `▶ Animations` / `⇄ Switch`. | Round 2 |
| R2‑3 | Animation template keeps the EfficientNet animation look. | Round 2 |
| R2‑4 | Tooling in Python 3, stdlib only. | Round 2 |
| R2‑5 | Placeholder labels use the file name only. | Round 2 |
| R2‑6 | P7 (port EfficientNet to the template) is part of the plan. | Round 2 |
| D‑1 | Deck navigation ignores keys while navigator/picker/animation overlay is open. | Spec, accepted |
| D‑2 | Title text from the slide's `.slide-title` element (HTML allowed); `data-title` only where no visible title exists. | Spec, accepted |
| D‑3 | Navigator rows show number + title only (original's subtitle line dropped). | Requirement |
| D‑4 | User zone first, engine/vendor block last in the file; CSS layering so user CSS always wins. | Spec, accepted |
