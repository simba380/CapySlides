/* Deck animation contract v__ENGINE_VERSION__. Source of truth: engine/anim-contract.js.
   Protocol v1 (SPEC §9.5) — ready handshake, key forwarding and presets — is implemented in P4.
   This block must stay in every animation file so tools/update.py can refresh it. */
(() => {
  'use strict';
  window.DeckAnim = { version: '__ENGINE_VERSION__', protocol: 1 };
})();
