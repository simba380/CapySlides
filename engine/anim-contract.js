/* Deck animation contract v__ENGINE_VERSION__ (protocol 1, SPEC §9.5). Source of truth: engine/anim-contract.js.
   Every animation file must contain this block (between the ANIM-CONTRACT markers, refreshed by
   tools/update.py). It lets a deck embed the animation:
     - ready handshake: tells the deck the file exists (otherwise the deck shows a placeholder),
     - key forwarding: navigation keys pressed inside the animation move the presentation,
     - presets: the deck can send { type: 'preset', preset } → window.applyPreset(preset) if defined,
     - animation steps: D = forward, A = back (pressed here, or in the deck and sent as
       { type: 'step', dir: 1 | -1 }) → window.animStep(dir) if defined: one of the animation's own steps.
   URL parameters set by the deck: deck-embed=1 (embedded), deck-thumb=1 (small preview), plus the
   slide's data-params, readable via DeckAnim.params. */
(() => {
  'use strict';

  const PARAMS = new URLSearchParams(location.search);
  const EMBEDDED = window.parent !== window;
  const NAV_KEYS = new Set(['ArrowRight', 'ArrowDown', ' ', 'Spacebar', 'PageDown', 'End',
                            'ArrowLeft', 'ArrowUp', 'PageUp', 'Home']);
  const ARROWS = new Set(['ArrowRight', 'ArrowLeft', 'ArrowUp', 'ArrowDown']);
  const TEXT_INPUT = 'textarea, select, input:not([type=range]):not([type=checkbox]):not([type=radio])' +
                     ':not([type=button]):not([type=submit]):not([type=reset]):not([type=color])';

  function post(message) {
    if (EMBEDDED) window.parent.postMessage({ ns: 'deck', v: 1, ...message }, '*');
  }

  function ready() {
    post({ type: 'ready', title: document.title });
  }

  window.addEventListener('message', e => {
    if (e.source !== window.parent) return;
    const data = e.data;
    if (!data || data.ns !== 'deck') return;
    if (data.type === 'ping') ready();
    else if (data.type === 'preset' && typeof window.applyPreset === 'function') window.applyPreset(data.preset || {});
    else if (data.type === 'step') step(data.dir === -1 ? -1 : 1);   // decks before 1.2.0 send no dir
  });

  function step(dir) {
    if (typeof window.animStep === 'function') window.animStep(dir);
  }

  function isTextInput(t) {
    return t instanceof Element && (t.isContentEditable || t.matches(TEXT_INPUT));
  }

  // D = one step forward, A = one step back inside the animation (decision R16-1, "gaming" keys), also
  // when not embedded. They never move the presentation, so the deck's Space/arrow keys keep their meaning.
  const STEP_KEYS = { d: 1, D: 1, a: -1, A: -1 };
  document.addEventListener('keydown', e => {
    if (!(e.key in STEP_KEYS) || e.ctrlKey || e.altKey || e.metaKey || isTextInput(e.target)) return;
    e.preventDefault();
    step(STEP_KEYS[e.key]);
  });

  // Navigation keys always go to the deck, even while a slider has focus (as in the original
  // deck). Ctrl/Shift + arrow keys stay inside the animation (decision R8-1). Typing in text
  // fields never navigates.
  document.addEventListener('keydown', e => {
    if (!EMBEDDED || !NAV_KEYS.has(e.key) || e.altKey || e.metaKey) return;
    if (ARROWS.has(e.key) && (e.ctrlKey || e.shiftKey)) return;
    if (isTextInput(e.target)) return;
    post({ type: 'key', key: e.key });
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();

  window.DeckAnim = {
    version: '__ENGINE_VERSION__',
    protocol: 1,
    embedded: EMBEDDED,
    thumbnail: PARAMS.has('deck-thumb'),
    params: PARAMS,
  };
})();
