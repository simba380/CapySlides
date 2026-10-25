# CustomPresentations — notes for AI agents

Single-file, offline HTML presentation template. **SPEC.md is the source of truth** for behaviour and decisions (§20 decision log is binding); work through the phases in SPEC §18 in order.

## Repository rules
- `engine/` is the source of truth for engine code (`deck.css`, `components.css`, `deck.js`, `anim-contract.js`) and for the template skeletons (`engine/shell/`). **Never hand-edit `template/*.html`.** They are generated.
- After any change in `engine/`, run:
  ```
  python tools/build.py
  python -m unittest discover tools/tests
  ```
  `python tools/build.py --check` fails if `template/` is stale.
- Engine behaviour is tested in `tools/tests/test_engine.py`: fixture decks (`tools/tests/fixtures/*.html`, shells with the `<!-- @@DECK_ENGINE@@ -->` placeholder) run in headless Edge/Chrome via `file://` with the network disabled. Built fixtures are left in `.tmp/fixtures/` for manual viewing. Add a fixture + test for every new engine feature.
- Open any deck with `?dev` (e.g. `…_presentation.html?dev`): the ☰ Slides navigator then lists every problem per slide (with the step where it shows; clicking jumps there), deck-wide problems in a red box on top, and the badge bottom-left. `Deck.warnings` / `Deck.problems` / `Deck.state` / `Deck.goTo()` are available in the console. `?preview=<index|id>[&step=k]` renders a single slide (used by thumbnails).
- Third-party assets are pinned in `engine/vendor/manifest.json` and hash-locked in `lock.json`. Change versions only via the manifest, then `python tools/fetch_vendor.py`. Never edit vendored files.
- Marker blocks (`DECK-ENGINE`, `ANIM-VENDOR`, `ANIM-CONTRACT`, see `tools/_blocks.py`) are a stable public contract. Don't change their format.
- Built files contain ~1 MB base64 lines inside the marker blocks. Don't read past a `:BEGIN` marker; read the sources in `engine/` instead.
- Tooling: Python 3 standard library only.
- Every `<img>` in a deck needs `width`/`height` = the image's natural size (SPEC §10.2). After adding or changing images, run `python tools/image_sizes.py path/to/X_presentation.html` (writes a `.bak`); `--check` only reports and exits 1 if any are missing or wrong.
- Animation files (`*_animations.html`) start from `template/template_animations.html` and must keep its `ANIM-VENDOR` and `ANIM-CONTRACT` blocks: without the contract's `ready` handshake a deck shows the file as missing. Register each file in `DECK.animations`; presets come from `data-params` via the URL (`readURLParams` / `window.applyPreset`).
- Steps are **0-based**: step 0 = slide title (+ anything with `data-step="0"`), steps 1…k = explicitly assigned content, one final step = all unmarked content (SPEC §8.3).
- Reuse components instead of writing per-slide CSS: classes in `engine/components.css`, copy-paste snippets in `engine/components.html` (also shown via the `?dev` **▦ Components** button). A new reusable component = CSS + a `<template>` entry there.
- `examples/components/` is the showcase deck (EfficientNet slides rebuilt with the components). Edit `components_presentation.src.html`; `tools/build.py` generates `components_presentation.html`. Never hand-edit the generated file.
- `docs/example_presentation_EfficientNet/` is the untouched visual/behavioural reference.

## Authoring decks
- `AUTHORING.md` is the guide for writing presentations (generated from `engine/AUTHORING.src.md` + the component catalog by `tools/build.py`; never edit it directly). `TOOLS.html` lists every command and helper — add any new tool there (a test enforces it).
- Presentation folders are **self-contained** and never depend on this repository (they get zipped and submitted). Tools only act on them: `tools/new.py` (create, interactive), `tools/check.py` (problems per slide/step), `tools/image_sizes.py`, `tools/update.py` (newer engine, content untouched), `tools/pack.py` (verified zip without CLAUDE.md/AUTHORING.md).
- Each presentation folder has a managed `CLAUDE.md` block (pointer to the central `AUTHORING.md` + version rule) and an `AUTHORING.md` copy matching its engine; `update.py` refreshes both.
- Compatibility: engine versions are semver. Within 1.x never change the meaning of existing attributes, classes or `DECK` fields; a breaking change needs 2.0 and migration notes in `AUTHORING.md`. Bump `engine/VERSION` for every engine release.
