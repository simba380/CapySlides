/* Deck engine v__ENGINE_VERSION__ — runtime. Source of truth: engine/deck.js (inlined by tools/build.py).
   Implements SPEC §6 canvas, §7 config, §8 slides/steps/navigation, §12.2–12.4 TOC/black/footer.
   Later phases plug in here: P2 title slide, top buttons, navigator, preview mode; P3 assets;
   P4 animations; P5 math escaping + components. */
(() => {
  'use strict';

  const VERSION = '__ENGINE_VERSION__';
  const PARAMS = new URLSearchParams(location.search);
  const DEV = PARAMS.has('dev');

  const SLIDE_TYPES = ['title', 'toc', 'content', 'animation', 'black'];
  const FRAMED_TYPES = ['toc', 'content', 'animation'];
  const LAYOUTS = ['full', 'center'];
  const STEP_FX = ['rise', 'fade', 'slide-left', 'none'];
  const FORWARD_KEYS = new Set(['ArrowRight', 'ArrowDown', ' ', 'Spacebar', 'PageDown', 'End']);
  const BACK_KEYS = new Set(['ArrowLeft', 'ArrowUp', 'PageUp', 'Home']);
  const MATH_DELIMITERS = [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '$',  right: '$',  display: false },
    { left: '\\(', right: '\\)', display: false },
  ];

  const DEFAULTS = {
    title: '',
    subtitle: '',
    presenter: 'Simon Meier',
    course: { title: '', type: '', semester: '' },
    cover: { background: 'images/eth_zurich_aerial.png', boxMaxWidth: '58%' },
    toc: [],
    animations: [],
    date: 'auto',
    canvas: { width: 1280, height: 800 },
    hooks: {},
  };

  // ── Warnings ──────────────────────────────────────────────────────────────
  // Authoring problems never stop the deck. They go to the console, and with ?dev
  // they are also listed in a badge (SPEC §7, decision R4-1).

  const warnings = [];

  function warn(message, el) {
    warnings.push(message);
    if (el) console.warn('[deck] ' + message, el);
    else console.warn('[deck] ' + message);
  }

  // ── Config ────────────────────────────────────────────────────────────────

  function readConfig() {
    // `const DECK` in the user zone is a global lexical binding, not a window property.
    const user = typeof DECK !== 'undefined' ? DECK : undefined;  // eslint-disable-line no-undef
    if (!user || typeof user !== 'object') {
      warn('no DECK config object found; using defaults');
    }
    const u = user && typeof user === 'object' ? user : {};
    const cfg = {
      ...DEFAULTS, ...u,
      course: { ...DEFAULTS.course, ...(u.course || {}) },
      cover:  { ...DEFAULTS.cover,  ...(u.cover  || {}) },
      canvas: { ...DEFAULTS.canvas, ...(u.canvas || {}) },
    };

    const { width, height } = cfg.canvas;
    if (!(width > 0 && height > 0 && isFinite(width) && isFinite(height))) {
      warn(`DECK.canvas must be { width, height } with positive numbers; using ${DEFAULTS.canvas.width}x${DEFAULTS.canvas.height}`);
      cfg.canvas = { ...DEFAULTS.canvas };
    }
    if (!Array.isArray(cfg.toc)) {
      warn('DECK.toc must be an array of strings or { text, sub: [...] } objects');
      cfg.toc = [];
    }
    if (!cfg.hooks || typeof cfg.hooks !== 'object') {
      warn('DECK.hooks must be an object mapping slide ids to functions');
      cfg.hooks = {};
    }
    for (const [id, fn] of Object.entries(cfg.hooks)) {
      if (typeof fn !== 'function') warn(`DECK.hooks["${id}"] is not a function`);
    }
    if (typeof cfg.date !== 'string' || !cfg.date.trim()) {
      warn("DECK.date must be 'auto' or a date string; using 'auto'");
      cfg.date = 'auto';
    }
    if (!String(cfg.title).trim()) warn('DECK.title is empty');
    return cfg;
  }

  // ── Small DOM helpers ─────────────────────────────────────────────────────

  function h(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function formatDate(d) {
    const pad = n => String(n).padStart(2, '0');
    return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()}`;
  }

  // ── Viewport / canvas (SPEC §6) ───────────────────────────────────────────

  let cfg, slides = [], viewport, stage;
  const state = { current: -1, locked: false, scale: 1 };

  function buildCanvas(deckEl) {
    viewport = h('div');
    viewport.id = 'deck-viewport';
    stage = h('div');
    stage.id = 'deck-stage';
    stage.style.width = cfg.canvas.width + 'px';
    stage.style.height = cfg.canvas.height + 'px';
    deckEl.parentNode.insertBefore(viewport, deckEl);
    viewport.appendChild(stage);
    stage.appendChild(deckEl);
  }

  function fit() {
    const { width: W, height: H } = cfg.canvas;
    const s = Math.min(window.innerWidth / W, window.innerHeight / H);
    const x = (window.innerWidth - W * s) / 2;
    const y = (window.innerHeight - H * s) / 2;
    stage.style.transform = `translate(${x}px, ${y}px) scale(${s})`;
    state.scale = s;
  }

  function updateLetterbox() {
    const slide = slides[state.current];
    if (!slide) return;
    const bg = getComputedStyle(slide.el).backgroundColor;
    viewport.style.backgroundColor = !bg || bg === 'transparent' || bg === 'rgba(0, 0, 0, 0)' ? '#fff' : bg;
  }

  // ── Steps (SPEC §8.3) ─────────────────────────────────────────────────────

  /** "3" → [3, ∞]; "2..4" → [2, 4]; anything invalid → null. */
  function parseRange(value) {
    const m = /^\s*(\d+)\s*(?:\.\.\s*(\d+)\s*)?$/.exec(String(value));
    if (!m) return null;
    const from = Number(m[1]);
    const to = m[2] === undefined ? Infinity : Number(m[2]);
    return from >= 1 && to >= from ? [from, to] : null;
  }

  function inRange(step, range) {
    return step >= range[0] && step <= range[1];
  }

  function parseSteps(slide) {
    const { el } = slide;
    const where = `slide ${slide.index + 1} ("${slide.id}")`;
    let highest = 1;
    const note = range => { highest = Math.max(highest, range[0], isFinite(range[1]) ? range[1] : 0); };

    if (el.querySelector('section')) warn(`${where}: nested <section> elements are not supported`);

    for (const layer of el.querySelectorAll('[data-step]')) {
      const range = parseRange(layer.dataset.step);
      if (!range) {
        warn(`${where}: invalid data-step="${layer.dataset.step}" (use "3", "2..4" or "3..3"); element stays visible`, layer);
        continue;
      }
      let fx = layer.dataset.stepFx || 'rise';
      if (!STEP_FX.includes(fx)) {
        warn(`${where}: unknown data-step-fx="${fx}" (use ${STEP_FX.join(', ')}); using rise`, layer);
        fx = 'rise';
      }
      layer.classList.add('step-layer', 'fx-' + fx);
      slide.layers.push({ el: layer, range });
      note(range);
    }

    for (const target of el.querySelectorAll('[data-step-class]')) {
      for (const rule of target.dataset.stepClass.trim().split(/\s+/).filter(Boolean)) {
        const cut = rule.lastIndexOf(':');
        const cls = cut > 0 ? rule.slice(0, cut) : '';
        const range = cut > 0 ? parseRange(rule.slice(cut + 1)) : null;
        if (!cls || !range) {
          warn(`${where}: invalid data-step-class rule "${rule}" (use "class:3" or "class:2..4")`, target);
          continue;
        }
        slide.classRules.push({ el: target, cls, range });
        note(range);
      }
    }

    let N = highest;
    if (el.dataset.steps !== undefined) {
      const declared = Number(el.dataset.steps);
      if (!Number.isInteger(declared) || declared < 1) {
        warn(`${where}: invalid data-steps="${el.dataset.steps}" (positive integer expected)`);
      } else {
        if (declared < highest) warn(`${where}: data-steps="${declared}" is lower than the highest step used (${highest})`);
        N = Math.max(declared, highest);
      }
    }
    slide.N = N;
  }

  // ── Slide construction (SPEC §8.1, §8.2, §12.2–12.4) ──────────────────────

  function buildFooter(label) {
    const footer = h('div', 'slide-footer');
    const logo = h('div', 'eth-logo', 'ETH ');
    logo.appendChild(h('span', '', 'zürich'));
    const num = h('div', 'slide-num');
    num.append(h('span', 'footer-date'), h('span', 'footer-number', label));
    footer.append(logo, num);
    return footer;
  }

  function wrapContent(slide) {
    const { el } = slide;
    const content = h('div', 'slide-content');
    const layout = el.dataset.layout;
    if (layout) {
      if (LAYOUTS.includes(layout)) content.classList.add('layout-' + layout);
      else warn(`slide ${slide.index + 1} ("${slide.id}"): unknown data-layout="${layout}" (use ${LAYOUTS.join(', ')})`);
    }
    while (el.firstChild) content.appendChild(el.firstChild);
    el.append(content, buildFooter(slide.label));
  }

  function renderToc(el) {
    el.appendChild(h('h2', 'slide-title', 'Table of Contents'));
    const list = h('ol', 'toc-list');
    cfg.toc.forEach((entry, i) => {
      const item = typeof entry === 'string' ? { text: entry } : entry;
      if (!item || typeof item.text !== 'string') {
        warn(`DECK.toc[${i}] must be a string or { text, sub: [...] }`);
        return;
      }
      const li = h('li', 'toc-item');
      const body = h('div', 'toc-body');
      body.appendChild(h('div', 'toc-text', item.text));
      if (item.sub !== undefined) {
        if (!Array.isArray(item.sub)) warn(`DECK.toc[${i}].sub must be an array of strings`);
        else {
          const sub = h('ul', 'toc-sub');
          item.sub.forEach(s => sub.appendChild(h('li', '', String(s))));
          body.appendChild(sub);
        }
      }
      li.append(h('span', 'num', String(list.children.length + 1)), body);
      list.appendChild(li);
    });
    el.appendChild(list);
  }

  function renderTitleStub(el) {
    // Minimal cover until the real title slide lands in P2.
    const box = h('div', 'title-stub');
    box.append(h('div', 'title-stub-title', cfg.title), h('div', 'title-stub-sub', cfg.subtitle),
               h('div', 'title-stub-presenter', cfg.presenter));
    el.appendChild(box);
  }

  function renderAnimationStub(slide) {
    const anim = slide.el.dataset.anim || '?';
    slide.el.appendChild(h('div', 'anim-stub', `Animation slide "${anim}" — rendered from P4 on`));
  }

  function slideTitle(slide) {
    const visible = slide.el.querySelector('.slide-title');
    const text = visible ? visible.textContent.trim() : '';
    if (text) return text;
    if (slide.el.dataset.title) return slide.el.dataset.title;
    if (slide.type === 'title') return String(cfg.title);
    if (slide.type === 'black') return 'End';
    warn(`slide ${slide.index + 1} ("${slide.id}") has no title (add <h2 class="slide-title"> or data-title)`);
    return `Slide ${slide.label || slide.index + 1}`;
  }

  function validateOrder() {
    const count = t => slides.filter(s => s.type === t).length;
    if (count('title') !== 1) warn(`expected exactly one title slide, found ${count('title')}`);
    else if (slides[0].type !== 'title') warn('the title slide must be the first slide');
    if (count('toc') !== 1) warn(`expected exactly one toc slide, found ${count('toc')}`);
    else if (!slides[1] || slides[1].type !== 'toc') warn('the toc slide must be the second slide');
    if (count('black') === 0) warn('no black slide: there is no end marker and no appendix');
    if (count('black') > 1) warn(`found ${count('black')} black slides; only the first one starts the appendix`);
    for (const s of slides) {
      if (s.zone === 'appendix' && (s.type === 'title' || s.type === 'toc')) {
        warn(`slide ${s.index + 1}: a ${s.type} slide cannot be in the appendix`);
      }
    }
  }

  function parseSlides(deckEl) {
    for (const child of deckEl.children) {
      if (child.tagName !== 'SECTION') warn(`<${child.tagName.toLowerCase()}> directly inside #deck is ignored; slides must be <section> elements`, child);
    }
    const sections = [...deckEl.children].filter(el => el.tagName === 'SECTION');
    const ids = new Set();
    let zone = 'main', mainCount = 0, appendixCount = 0, seenBlack = false;

    slides = sections.map((el, index) => {
      let type = el.dataset.type;
      if (!SLIDE_TYPES.includes(type)) {
        warn(`slide ${index + 1}: unknown data-type="${type ?? ''}" (use ${SLIDE_TYPES.join(', ')}); treated as content`, el);
        type = 'content';
      }
      if (!el.id) el.id = `slide-${index + 1}`;
      if (ids.has(el.id)) warn(`duplicate slide id "${el.id}"`, el);
      ids.add(el.id);

      let label = '';
      let number = null;
      if (type === 'black') {
        if (!seenBlack) zone = 'appendix';
        seenBlack = true;
      } else if (zone === 'main') {
        number = ++mainCount;
        label = String(number);
      } else {
        number = ++appendixCount;
        label = `Appendix ${number}`;
      }

      el.classList.add('slide', 'slide--' + type);
      if (el.dataset.bgColor) el.style.backgroundColor = el.dataset.bgColor;
      return {
        el, index, type, id: el.id, zone: type === 'black' ? 'main' : zone, number, label,
        title: '', N: 1, layers: [], classRules: [], step: 1, visited: false, rendered: false,
      };
    });

    validateOrder();

    for (const slide of slides) {
      const { el, type } = slide;
      const empty = el.children.length === 0;
      if (type === 'title' && empty) renderTitleStub(el);
      if (type === 'toc' && empty) renderToc(el);
      if (type === 'animation') renderAnimationStub(slide);
      if (type === 'black' && !empty) warn(`slide ${slide.index + 1}: the black slide should be empty; its content is hidden`);
      if (FRAMED_TYPES.includes(type)) wrapContent(slide);
      slide.title = slideTitle(slide);
      parseSteps(slide);
    }

    for (const id of Object.keys(cfg.hooks)) {
      if (!ids.has(id)) warn(`DECK.hooks["${id}"] does not match any slide id`);
    }
  }

  // ── Rendering + navigation (SPEC §8.3, §8.4) ──────────────────────────────

  function renderSlide(slide) {
    const step = slide.step;
    for (const { el, range } of slide.layers) el.classList.toggle('is-shown', inRange(step, range));
    for (const { el, cls, range } of slide.classRules) el.classList.toggle(cls, inRange(step, range));
    const hook = cfg.hooks[slide.id];
    if (typeof hook === 'function') {
      try {
        hook(step, slide.el, { preview: false, first: !slide.rendered, N: slide.N });
      } catch (err) {
        warn(`DECK.hooks["${slide.id}"] threw: ${err && err.message ? err.message : err}`);
      }
    }
    slide.rendered = true;
  }

  function show(index, how) {
    const slide = slides[index];
    if (!slide.visited) {
      slide.step = how === 'back' ? slide.N : 1;
      slide.visited = true;
    }
    const previous = slides[state.current];
    if (previous && previous !== slide) {
      previous.el.classList.remove('is-active');
      previous.el.inert = true;
    }
    state.current = index;
    slide.el.classList.add('is-active');
    slide.el.inert = false;
    renderSlide(slide);
    updateLetterbox();
  }

  function next() {
    if (state.locked) return false;
    const slide = slides[state.current];
    if (slide.step < slide.N) { slide.step++; renderSlide(slide); return true; }
    if (state.current < slides.length - 1) { show(state.current + 1, 'forward'); return true; }
    return false;
  }

  function prev() {
    if (state.locked) return false;
    const slide = slides[state.current];
    if (slide.step > 1) { slide.step--; renderSlide(slide); return true; }
    if (state.current > 0) { show(state.current - 1, 'back'); return true; }
    return false;
  }

  /** Jump to a slide by 0-based index or by id; optionally set its step (clamped to 1…N). */
  function goTo(target, step) {
    const index = typeof target === 'string' ? slides.findIndex(s => s.id === target) : target;
    if (!Number.isInteger(index) || index < 0 || index >= slides.length) {
      warn(`Deck.goTo: no slide ${JSON.stringify(target)}`);
      return false;
    }
    if (step !== undefined) {
      const slide = slides[index];
      slide.step = Math.min(slide.N, Math.max(1, Math.round(Number(step)) || 1));
      slide.visited = true;
    }
    show(index, 'jump');
    return true;
  }

  // ── Input (SPEC §8.4, decision R4-4) ──────────────────────────────────────

  function isEditable(target) {
    return target instanceof Element &&
      (target.isContentEditable || !!target.closest('input, textarea, select, [contenteditable]'));
  }

  function onKeyDown(e) {
    if (e.defaultPrevented || e.altKey || e.metaKey || isEditable(e.target)) return;
    const forward = FORWARD_KEYS.has(e.key);
    if (!forward && !BACK_KEYS.has(e.key)) return;
    e.preventDefault();
    if (forward) next(); else prev();
  }

  // ── Footer date (SPEC §12.4) ──────────────────────────────────────────────

  function renderDates() {
    const text = cfg.date === 'auto' ? formatDate(new Date()) : cfg.date;
    for (const el of document.querySelectorAll('#deck .footer-date')) el.textContent = text;
  }

  function scheduleMidnightRefresh() {
    const now = new Date();
    const nextDay = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1, 0, 0, 1);
    setTimeout(() => { renderDates(); scheduleMidnightRefresh(); }, nextDay - now);
  }

  // ── Math ──────────────────────────────────────────────────────────────────

  function renderMath(root) {
    if (typeof window.renderMathInElement !== 'function') {
      warn('KaTeX auto-render is not available; formulas stay as source text');
      return;
    }
    // With throwOnError:false KaTeX shows unknown commands in red instead of failing, so
    // problems are detected separately: a formula that parses in neither mode is reported.
    const check = math => {
      let error;
      for (const displayMode of [false, true]) {
        try { window.katex.renderToString(math, { displayMode, throwOnError: true }); return math; }
        catch (err) { error = err; }
      }
      warn(`formula error in "${math}": ${error && error.message ? error.message : error}`);
      return math;
    };
    window.renderMathInElement(root, {
      delimiters: MATH_DELIMITERS,
      throwOnError: false,
      preProcess: check,
      errorCallback: (message, err) => warn(`formula error: ${message} ${err || ''}`.trim()),
    });
  }

  // ── Dev badge (decision R4-1) ─────────────────────────────────────────────

  function renderBadge() {
    const badge = h('div');
    badge.id = 'deck-warnings';
    badge.className = warnings.length ? 'has-warnings' : 'no-warnings';
    const toggle = h('button', 'dw-toggle', warnings.length
      ? `⚠ ${warnings.length} deck warning${warnings.length === 1 ? '' : 's'}`
      : '✓ no deck warnings');
    const close = h('button', 'dw-close', '×');
    close.title = 'Hide (reload to show again)';
    const list = h('ol', 'dw-list');
    warnings.forEach(w => list.appendChild(h('li', '', w)));
    toggle.addEventListener('click', () => badge.classList.toggle('open'));
    close.addEventListener('click', () => badge.remove());
    badge.append(toggle, close, list);
    document.body.appendChild(badge);
  }

  // ── Boot (SPEC §17) ───────────────────────────────────────────────────────

  function summary(s) {
    return { index: s.index, id: s.id, type: s.type, zone: s.zone, label: s.label,
             title: s.title, N: s.N, step: s.step, visited: s.visited };
  }

  window.Deck = {
    version: VERSION,
    dev: DEV,
    warnings,
    get slides() { return slides.map(summary); },
    get state() {
      const s = slides[state.current];
      return { current: state.current, id: s && s.id, step: s && s.step, N: s && s.N,
               label: s && s.label, locked: state.locked, scale: state.scale };
    },
    next, prev, goTo,
    fit: () => fit(),
  };

  function boot() {
    const deckEl = document.getElementById('deck');
    try {
      cfg = readConfig();
      if (!deckEl) throw new Error('no <main id="deck"> element found');
      buildCanvas(deckEl);
      parseSlides(deckEl);
      renderMath(deckEl);
      renderDates();
      if (cfg.date === 'auto') scheduleMidnightRefresh();
      fit();
      window.addEventListener('resize', fit);
      document.addEventListener('keydown', onKeyDown);
      if (slides.length) {
        slides.forEach(s => { s.el.inert = true; });
        show(0, 'forward');
      } else {
        warn('the deck has no slides');
      }
    } catch (err) {
      warn(`engine failed to start: ${err && err.message ? err.message : err}`);
      console.error(err);
    } finally {
      document.documentElement.classList.remove('deck-loading');
      if (DEV) renderBadge();
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
