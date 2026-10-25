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
- `docs/example_presentation_EfficientNet/` is the untouched visual/behavioural reference.

## Authoring decks
A guide for filling in presentations (`AUTHORING.md`) is added in phase P6.
