/* Deck animation contract v__ENGINE_VERSION__ (protocol 1, SPEC §9.5). Source of truth: engine/anim-contract.js.
   Every animation file must contain this block (between the ANIM-CONTRACT markers, refreshed by
   tools/update.py). It lets a deck embed the animation:
     - ready handshake: tells the deck the file exists (otherwise the deck shows a placeholder),
     - key forwarding: navigation keys pressed inside the animation move the presentation,
     - presets: the deck can send { type: 'preset', preset } → window.applyPreset(preset) if defined,
     - animation steps: the A key (pressed here, or in the deck and sent as { type: 'step' })
       → window.animStep() if defined: advances the animation by one of its own steps.
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
    else if (data.type === 'step') step();
  });

  function step() {
    if (typeof window.animStep === 'function') window.animStep();
  }

  function isTextInput(t) {
    return t instanceof Element && (t.isContentEditable || t.matches(TEXT_INPUT));
  }

  // A = one step forward inside the animation (decision R15-1), also when not embedded. It never
  // moves the presentation, so the deck's Space/arrow keys keep their meaning.
  document.addEventListener('keydown', e => {
    if ((e.key !== 'a' && e.key !== 'A') || e.ctrlKey || e.altKey || e.metaKey || isTextInput(e.target)) return;
    e.preventDefault();
    step();
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
