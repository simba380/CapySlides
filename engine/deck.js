/* Deck engine v__ENGINE_VERSION__ — runtime. Source of truth: engine/deck.js (inlined by tools/build.py).
   P0 skeleton: renders math and reveals the deck. Slides, steps and navigation follow in P1+. */
(() => {
  'use strict';

  const VERSION = '__ENGINE_VERSION__';

  const MATH_DELIMITERS = [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '$',  right: '$',  display: false },
    { left: '\\(', right: '\\)', display: false },
  ];

  function renderMath(root) {
    if (typeof window.renderMathInElement !== 'function') return;
    window.renderMathInElement(root, { delimiters: MATH_DELIMITERS, throwOnError: false });
  }

  function boot() {
    const deck = document.getElementById('deck');
    if (deck) renderMath(deck);
    document.documentElement.classList.remove('deck-loading');
  }

  window.Deck = { version: VERSION };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
