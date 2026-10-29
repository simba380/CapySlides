# CapySlides — instructions for AI agents

Offline, single-file HTML presentations (ETH style) with step reveals, KaTeX, interactive animations
and tooling. Start with `README.md` (overview), `AUTHORING.md` (how to write slides),
`TOOLS.html` (every command), `SPEC.md` (design + binding decision log §20).

Most tasks are one of two kinds. Find out which one first.

## A. Creating or editing a presentation (the common case)

A presentation is a self-contained project folder `presentations/<name>/` (the user zips and
submits it; it must never depend on this repository).

1. New presentation: `python tools/new.py <name>` (interactive; answers can be piped, one per line).
   Another animation for an existing project: `python tools/add_animation.py presentations/<name> "Name"`
   (never copy animation files by hand).
2. Read `AUTHORING.md` §1–§8 before writing slides. Key rules:
   - Edit only the **user zone** of `<name>_presentation.html`: `<style id="deck-user-styles">`,
     `const DECK = {…}`, and the `<section>`s in `<main id="deck">`.
   - **Never read or edit past `<!-- DECK-ENGINE:BEGIN`** (≈1 MB generated code, base64 on very long
     lines). Same for `ANIM-VENDOR` / `ANIM-CONTRACT` in animation files.
   - Steps are **0-based**: `data-step="0"` = with the title; `"1"`, `"2"`, … = one per click;
     unmarked content = one final step.
   - Reuse the components (§7 of AUTHORING.md, `?dev` → ▦ Components) instead of new CSS.
   - Images go into `images/`; every `<img>` needs `width`/`height` → `python tools/image_sizes.py <deck>`.
   - Never reference files outside the project folder (no `../`, absolute paths or URLs).
3. After every change: `python tools/check.py presentations/<name>`; fix everything it reports
   (exit code 0 = clean).
4. If the deck's engine version is older than `engine/VERSION`: `python tools/update.py presentations/<name>`
   first (only the generated blocks change).
5. Submission: `python tools/pack.py presentations/<name>` → `presentations/<name>.zip`.

`presentations/EfficientNet/` is a complete real example (the original talk rebuilt).
`docs/example_presentation_EfficientNet/` is the untouched original — never edit it.

## B. Changing the template, engine or tools

- **Source of truth:** `engine/` (`deck.js`, `deck.css`, `components.css`, `components.html`,
  `anim-contract.js`, `shell/*.html`, `AUTHORING.src.md`, `VERSION`). `template/*.html` and
  `AUTHORING.md` are generated — never hand-edit them.
- After every engine change:
  ```
  python tools/build.py
  python -m unittest discover tools/tests
  ```
  `python tools/build.py --check` fails if a generated file is stale.
- **Version:** bump `engine/VERSION` (semver) for every engine change, then update the example
  project: `python tools/update.py presentations/EfficientNet` (delete the `.bak` files afterwards).
  Within 1.x never change the meaning of existing attributes, classes or `DECK` fields; breaking
  changes need 2.0 and migration notes in `engine/AUTHORING.src.md`.
- **Tests:** engine tests run fixture decks (`tools/tests/fixtures/*.html`, shells with
  `<!-- @@DECK_ENGINE@@ -->`) in headless Chrome/Edge via `file://` with the network blocked
  (`tools/_browser.py` picks a browser that really works; tests skip without one). Built fixtures
  stay in `.tmp/fixtures/`. Add a fixture + test for every engine feature and every bug fix. Probes
  share helper names (`$`, `vis`, `st`, `key`) — don't redeclare them.
- **Components:** a reusable component = CSS in `engine/components.css` + a `<template>` in
  `engine/components.html` (shown in the ▦ Components panel and in AUTHORING.md).
- **Tools:** Python 3 standard library only. Every `tools/*.py` script must be documented in
  `TOOLS.html` (a test enforces it). Shared helpers: `_blocks.py` (marker blocks — a stable public
  contract, don't change the format), `_browser.py` (headless runs), `_deckfolder.py` (projects,
  versions, the managed CLAUDE.md block).
- **Vendored assets** (fonts, KaTeX) are pinned in `engine/vendor/manifest.json` and hash-locked in
  `lock.json`; change them only via the manifest + `python tools/fetch_vendor.py`.
- **Decisions:** record behaviour changes in `SPEC.md` (§20 decision log) and keep `README.md`,
  `AUTHORING.src.md` and `TOOLS.html` in sync.

## Debugging a deck

Open it in Chrome/Edge with `?dev`: the ☰ Slides navigator lists every problem per slide and step
(click jumps there), deck-wide problems in a red box, a badge bottom-left, ▦ Components. Console:
`Deck.state`, `Deck.problems`, `Deck.goTo(id, step)`, `Deck.animations`. `?preview=<index|id>&step=k`
renders one slide.
