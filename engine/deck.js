/* Deck engine v__ENGINE_VERSION__ — runtime. Source of truth: engine/deck.js (inlined by tools/build.py).
   Implements SPEC §6 canvas, §7 config, §8 slides/steps/navigation, §11 preview mode,
   §12 title/TOC/black/footer/top buttons/navigator (incl. dev problems).
   §10 assets (missing images → placeholders), §9 animations, §13 math, §14 components
   (code highlighting + the ?dev component catalog). */
(() => {
  'use strict';

  const VERSION = '__ENGINE_VERSION__';
  const PARAMS = new URLSearchParams(location.search);
  const PREVIEW = PARAMS.has('preview');   // thumbnail rendering inside an iframe (SPEC §11)
  const DEV = PARAMS.has('dev') && !PREVIEW;

  const SLIDE_TYPES = ['title', 'toc', 'content', 'animation', 'black'];
  const FRAMED_TYPES = ['toc', 'content', 'animation'];
  const IMPLICIT_STEP_TYPES = ['toc', 'content'];   // unmarked content appears at the final step (R9-1)
  const LAYOUTS = ['full', 'center'];
  const STEP_FX = ['rise', 'fade', 'slide-left', 'none'];
  const FORWARD_KEYS = new Set(['ArrowRight', 'ArrowDown', ' ', 'Spacebar', 'PageDown', 'End']);
  const BACK_KEYS = new Set(['ArrowLeft', 'ArrowUp', 'PageUp', 'Home']);
  const NOT_CONTENT = new Set(['SCRIPT', 'STYLE', 'TEMPLATE']);
  const MATH_DELIMITERS = [
    { left: '$$', right: '$$', display: true },
    { left: '\\[', right: '\\]', display: true },
    { left: '$',  right: '$',  display: false },
    { left: '\\(', right: '\\)', display: false },
  ];
  const THUMB_WIDTH = 126;   // navigator thumbnails (original 112px x 1.125)
  const HINT_MS = 4000;      // "← → to navigate" fades after this
  const DOLLAR = '\uE024';   // stands in for an escaped \$ while KaTeX scans the text
  const MATH_IGNORE = 'script, noscript, style, textarea, pre, code, option';
  // Component catalog from engine/components.html (injected by tools/build.py): [{ name, from, html }].
  const COMPONENTS = __COMPONENT_CATALOG__;
  const ANIM_READY_MS = 1500;   // after an animation iframe's load event, a `ready` must have arrived …
  const ANIM_TOTAL_MS = 4000;   // … and at the latest this long after its src was set (SPEC §9.5)
  const QUEUE_STEP_MS = 5000;   // a queued iframe that never fires `load` no longer blocks the queue

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

  let cfg, slides = [], sectionEls = [], viewport, stage, topbar;
  let anims = [];                        // validated DECK.animations, in their fixed global order
  const animById = new Map();
  const state = { current: -1, locked: false, animOpen: null, scale: 1 };

  /** Navigation is paused while a panel (navigator, picker) or an animation overlay is open. */
  function isBlocked() {
    return state.locked || state.animOpen !== null;
  }

  // ── Problems / warnings ───────────────────────────────────────────────────
  // Authoring problems never stop the deck. Each one is logged to the console and kept with
  // the slide (and element / step) it belongs to; with ?dev they are listed in the badge and
  // inside the ☰ Slides navigator (SPEC §7, §12.6).

  const problems = [];   // { message, slide: index | null, el: Element | null, step: number | null }
  const warnings = [];   // messages only (public, Deck.warnings)
  const layerRanges = new Map();   // step-layer element → [from, to]

  function slideIndexOf(el) {
    const section = el && el.closest ? el.closest('#deck > section') : null;
    const i = sectionEls.indexOf(section);
    return i >= 0 ? i : null;
  }

  /** warn(message, { slide?: index, el?: element, step?: number }) */
  function warn(message, where = {}) {
    const slide = where.slide !== undefined ? where.slide : slideIndexOf(where.el);
    problems.push({ message, slide: slide === undefined ? null : slide,
                    el: where.el || null, step: where.step ?? null });
    warnings.push(message);
    if (where.el) console.warn('[deck] ' + message, where.el);
    else console.warn('[deck] ' + message);
    refreshDevUi();
  }

  /** First step at which `el` is visible: the latest start of the step layers around it. */
  function firstVisibleStep(el) {
    let step = 0;
    for (let n = el; n && n.parentElement && n.parentElement.id !== 'deck'; n = n.parentElement) {
      const range = layerRanges.get(n);
      if (range) step = Math.max(step, range[0]);
    }
    return step;
  }

  /** Step at which a problem becomes visible (R6-4): explicit step, else its element's step, else 0. */
  function problemStep(p) {
    if (p.step !== null && p.step !== undefined) return p.step;
    if (p.el && p.el.isConnected) return firstVisibleStep(p.el);
    return 0;
  }

  // ── Config ────────────────────────────────────────────────────────────────

  function readConfig() {
    // `const DECK` in the user zone is a global lexical binding, not a window property.
    const user = typeof DECK !== 'undefined' ? DECK : undefined;  // eslint-disable-line no-undef
    if (!user || typeof user !== 'object') warn('no DECK config object found; using defaults');
    const u = user && typeof user === 'object' ? user : {};
    const c = {
      ...DEFAULTS, ...u,
      course: { ...DEFAULTS.course, ...(u.course || {}) },
      cover:  { ...DEFAULTS.cover,  ...(u.cover  || {}) },
      canvas: { ...DEFAULTS.canvas, ...(u.canvas || {}) },
    };

    const { width, height } = c.canvas;
    if (!(width > 0 && height > 0 && isFinite(width) && isFinite(height))) {
      warn(`DECK.canvas must be { width, height } with positive numbers; using ${DEFAULTS.canvas.width}x${DEFAULTS.canvas.height}`);
      c.canvas = { ...DEFAULTS.canvas };
    }
    if (!Array.isArray(c.toc)) {
      warn('DECK.toc must be an array of strings or { text, sub: [...] } objects');
      c.toc = [];
    }
    if (!c.hooks || typeof c.hooks !== 'object') {
      warn('DECK.hooks must be an object mapping slide ids to functions');
      c.hooks = {};
    }
    for (const [id, fn] of Object.entries(c.hooks)) {
      if (typeof fn !== 'function') warn(`DECK.hooks["${id}"] is not a function`);
    }
    if (typeof c.date !== 'string' || !c.date.trim()) {
      warn("DECK.date must be 'auto' or a date string; using 'auto'");
      c.date = 'auto';
    }
    if (!String(c.title).trim()) warn('DECK.title is empty');
    if (!Array.isArray(c.animations)) {
      warn('DECK.animations must be an array of { id, name, file } objects');
      c.animations = [];
    }
    c.animations.forEach((a, i) => {
      if (!a || typeof a !== 'object' || typeof a.id !== 'string' || !a.id || typeof a.file !== 'string' || !a.file) {
        warn(`DECK.animations[${i}] needs a non-empty id and file`);
        return;
      }
      if (animById.has(a.id)) { warn(`DECK.animations: duplicate id "${a.id}"`); return; }
      const anim = { id: a.id, name: typeof a.name === 'string' && a.name ? a.name : a.id, file: a.file };
      checkInsideFolder('animation file', a.file);
      animById.set(anim.id, anim);
      anims.push(anim);
    });
    return c;
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

  /** Steps are 0-based (R10-1): "3" → [3, ∞]; "2..4" → [2, 4]; "0" = with the title; invalid → null. */
  function parseRange(value) {
    const m = /^\s*(\d+)\s*(?:\.\.\s*(\d+)\s*)?$/.exec(String(value));
    if (!m) return null;
    const from = Number(m[1]);
    const to = m[2] === undefined ? Infinity : Number(m[2]);
    return from >= 0 && to >= from ? [from, to] : null;
  }

  function inRange(step, range) {
    return step >= range[0] && step <= range[1];
  }

  /** Unmarked content (R9-1, 0-based since R10-1): step 0 shows the slide title, steps 1…k show
      what is explicitly assigned to them, and one final step k+1 reveals everything that was not
      assigned to a step. Collects the unmarked content subtrees; a container that holds explicitly
      stepped elements stays structural and the search continues inside it, so `data-step="0"`
      anywhere still means "visible from the start". */
  function unmarkedContent(container, found = []) {
    for (const child of container.children) {
      if (NOT_CONTENT.has(child.tagName) || child.classList.contains('slide-title')) continue;
      if (child.hasAttribute('data-step')) continue;
      if (child.querySelector('[data-step]')) unmarkedContent(child, found);
      else found.push(child);
    }
    return found;
  }

  function parseSteps(slide) {
    const { el } = slide;
    const where = `slide ${slide.index + 1} ("${slide.id}")`;
    const at = extra => ({ slide: slide.index, ...extra });
    let highest = 0;   // highest step index referenced; steps run 0 … N-1
    const note = range => { highest = Math.max(highest, range[0], isFinite(range[1]) ? range[1] : 0); };

    if (el.querySelector('section')) warn(`${where}: nested <section> elements are not supported`, at());
    const unmarked = IMPLICIT_STEP_TYPES.includes(slide.type)
      ? unmarkedContent(el.querySelector('.slide-content') || el) : [];

    for (const layer of el.querySelectorAll('[data-step]')) {
      const range = parseRange(layer.dataset.step);
      if (!range) {
        warn(`${where}: invalid data-step="${layer.dataset.step}" (use "3", "2..4" or "3..3"); element stays visible`, at({ el: layer }));
        continue;
      }
      let fx = layer.dataset.stepFx || 'rise';
      if (!STEP_FX.includes(fx)) {
        warn(`${where}: unknown data-step-fx="${fx}" (use ${STEP_FX.join(', ')}); using rise`, at({ el: layer }));
        fx = 'rise';
      }
      layer.classList.add('step-layer', 'fx-' + fx);
      slide.layers.push({ el: layer, range });
      layerRanges.set(layer, range);
      note(range);
    }

    for (const target of el.querySelectorAll('[data-step-class]')) {
      for (const rule of target.dataset.stepClass.trim().split(/\s+/).filter(Boolean)) {
        const cut = rule.lastIndexOf(':');
        const cls = cut > 0 ? rule.slice(0, cut) : '';
        const range = cut > 0 ? parseRange(rule.slice(cut + 1)) : null;
        if (!cls || !range) {
          warn(`${where}: invalid data-step-class rule "${rule}" (use "class:3" or "class:2..4")`, at({ el: target }));
          continue;
        }
        slide.classRules.push({ el: target, cls, range });
        note(range);
      }
    }

    let N = highest + 1;   // number of steps
    if (el.dataset.steps !== undefined) {
      const declared = Number(el.dataset.steps);
      if (!Number.isInteger(declared) || declared < 1) {
        warn(`${where}: invalid data-steps="${el.dataset.steps}" (positive integer expected)`, at());
      } else {
        if (declared < N) warn(`${where}: data-steps="${declared}" is lower than the number of steps used (${N})`, at());
        N = Math.max(declared, N);
      }
    }
    if (unmarked.length) {   // the final step: everything not assigned to a numbered step
      const final = N;
      N += 1;
      for (const child of unmarked) {
        child.setAttribute('data-step', String(final));
        child.setAttribute('data-step-implicit', '');
        child.classList.add('step-layer', 'fx-rise');
        slide.layers.push({ el: child, range: [final, Infinity] });
        layerRanges.set(child, [final, Infinity]);
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
    if (slide.type === 'animation') content.classList.add('layout-full');   // the iframe fills the slide
    const layout = el.dataset.layout;
    if (layout) {
      if (LAYOUTS.includes(layout)) content.classList.add('layout-' + layout);
      else warn(`slide ${slide.index + 1} ("${slide.id}"): unknown data-layout="${layout}" (use ${LAYOUTS.join(', ')})`, { slide: slide.index });
    }
    while (el.firstChild) content.appendChild(el.firstChild);
    el.append(content, buildFooter(slide.label));
  }

  function renderToc(slide) {
    const { el } = slide;
    el.appendChild(h('h2', 'slide-title', 'Table of Contents'));
    const list = h('ol', 'toc-list');
    cfg.toc.forEach((entry, i) => {
      const item = typeof entry === 'string' ? { text: entry } : entry;
      if (!item || typeof item.text !== 'string') {
        warn(`DECK.toc[${i}] must be a string or { text, sub: [...] }`, { slide: slide.index });
        return;
      }
      const li = h('li', 'toc-item');
      const body = h('div', 'toc-body');
      body.appendChild(h('div', 'toc-text', item.text));
      if (item.sub !== undefined) {
        if (!Array.isArray(item.sub)) warn(`DECK.toc[${i}].sub must be an array of strings`, { slide: slide.index });
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

  // ── Title slide (SPEC §12.1) ──────────────────────────────────────────────

  function renderCover(slide) {
    const { el } = slide;
    if (el.children.length) {
      warn(`slide ${slide.index + 1}: title slide content is ignored; the cover is rendered from DECK`, { slide: slide.index });
      const ignored = h('div', 'cover-ignored');
      ignored.hidden = true;
      while (el.firstChild) ignored.appendChild(el.firstChild);
      el.appendChild(ignored);
    }
    const bg = h('div', 'cover-bg');
    if (cfg.cover.background) bg.dataset.bg = String(cfg.cover.background);   // loaded by initBackgrounds

    const logo = h('div', 'cover-eth', 'ETH ');
    logo.appendChild(h('span', '', 'zürich'));

    const header = h('div', 'cover-header');
    const { title, type, semester } = cfg.course;
    const lines = [title, [type, semester].filter(Boolean).join(', ')].filter(Boolean);
    lines.forEach(line => header.appendChild(h('div', '', String(line))));
    header.hidden = !lines.length;

    const box = h('div', 'cover-box');
    box.style.maxWidth = String(cfg.cover.boxMaxWidth);
    box.appendChild(h('div', 'cover-title', String(cfg.title)));
    if (String(cfg.subtitle).trim()) box.appendChild(h('div', 'cover-subtitle', String(cfg.subtitle)));
    box.appendChild(h('div', 'cover-presenter', String(cfg.presenter)));

    el.append(bg, logo, header, box);
  }

  /** Shrink the blue box to its longest rendered line: CSS max-content alone would keep the full
      max-width as soon as the title wraps. Measured in canvas px (screen px / stage scale). */
  function fitCoverBox() {
    for (const box of document.querySelectorAll('#deck .cover-box')) {
      box.style.width = '';
      let longest = 0;
      for (const text of box.children) {
        const range = document.createRange();
        range.selectNodeContents(text);
        for (const r of range.getClientRects()) longest = Math.max(longest, r.width / state.scale);
      }
      const cs = getComputedStyle(box);
      const padding = parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight);
      if (longest > 0) box.style.width = Math.ceil(longest + padding + 1) + 'px';
    }
  }

  function renderAnimationSlide(slide) {
    const id = slide.el.dataset.anim;
    const anim = animById.get(id);
    const where = `slide ${slide.index + 1} ("${slide.id}")`;
    if (!id) warn(`${where}: animation slide without data-anim (use an id from DECK.animations)`, { slide: slide.index });
    else if (!anim) warn(`${where}: unknown animation id "${id}" (not in DECK.animations)`, { slide: slide.index });
    const rec = createAnimFrame(anim, 'slide', { params: slide.el.dataset.params, slide: slide.index, missingName: id || '?' });
    slide.el.appendChild(rec.box);
  }

  function slideTitle(slide) {
    const visible = slide.el.querySelector('.slide-title');
    const text = visible ? visible.textContent.trim() : '';
    if (text) return text;
    if (slide.el.dataset.title) return slide.el.dataset.title;
    if (slide.type === 'title') return String(cfg.title);
    if (slide.type === 'black') return 'End';
    warn(`slide ${slide.index + 1} ("${slide.id}") has no title (add <h2 class="slide-title"> or data-title)`, { slide: slide.index });
    return `Slide ${slide.label || slide.index + 1}`;
  }

  function validateOrder() {
    const count = t => slides.filter(s => s.type === t).length;
    const first = t => { const s = slides.find(x => x.type === t); return s ? s.index : null; };
    if (count('title') !== 1) warn(`expected exactly one title slide, found ${count('title')}`);
    else if (slides[0].type !== 'title') warn('the title slide must be the first slide', { slide: first('title') });
    if (count('toc') !== 1) warn(`expected exactly one toc slide, found ${count('toc')}`);
    else if (!slides[1] || slides[1].type !== 'toc') warn('the toc slide must be the second slide', { slide: first('toc') });
    if (count('black') === 0) warn('no black slide: there is no end marker and no appendix');
    if (count('black') > 1) warn(`found ${count('black')} black slides; only the first one starts the appendix`);
    for (const s of slides) {
      if (s.zone === 'appendix' && (s.type === 'title' || s.type === 'toc')) {
        warn(`slide ${s.index + 1}: a ${s.type} slide cannot be in the appendix`, { slide: s.index });
      }
    }
  }

  function parseSlides(deckEl) {
    for (const child of deckEl.children) {
      if (child.tagName !== 'SECTION') warn(`<${child.tagName.toLowerCase()}> directly inside #deck is ignored; slides must be <section> elements`, { el: child });
    }
    sectionEls = [...deckEl.children].filter(el => el.tagName === 'SECTION');
    const ids = new Set();
    let zone = 'main', mainCount = 0, appendixCount = 0, seenBlack = false;

    slides = sectionEls.map((el, index) => {
      let type = el.dataset.type;
      if (!SLIDE_TYPES.includes(type)) {
        warn(`slide ${index + 1}: unknown data-type="${type ?? ''}" (use ${SLIDE_TYPES.join(', ')}); treated as content`, { slide: index, el });
        type = 'content';
      }
      if (!el.id) el.id = `slide-${index + 1}`;
      if (ids.has(el.id)) warn(`duplicate slide id "${el.id}"`, { slide: index, el });
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
        title: '', N: 1, layers: [], classRules: [], step: 0, visited: false, rendered: false,
      };
    });

    validateOrder();

    for (const slide of slides) {
      const { el, type } = slide;
      const empty = el.children.length === 0;
      if (type === 'title') renderCover(slide);
      if (type === 'toc' && empty) renderToc(slide);
      if (type === 'animation') renderAnimationSlide(slide);
      if (type === 'black' && !empty) warn(`slide ${slide.index + 1}: the black slide should be empty; its content is hidden`, { slide: slide.index });
      if (FRAMED_TYPES.includes(type)) wrapContent(slide);
      slide.title = slideTitle(slide);
      if (type !== 'title') parseSteps(slide);   // the cover is a single step
    }

    for (const id of Object.keys(cfg.hooks)) {
      if (!ids.has(id)) warn(`DECK.hooks["${id}"] does not match any slide id`);
    }
  }

  // ── Assets (SPEC §10): missing images become labelled placeholders ────────
  // A missing <img> keeps its element (so every CSS rule and step attribute still applies) and
  // gets a white, bordered SVG of its declared width × height as src. Backgrounds are declared
  // with data-bg so they can be preloaded and replaced the same way.

  const ABS_URL_RE = /url\(\s*['"]?(?!data:)/i;

  /** A presentation folder must stay self-contained (zip + submit, R12-3): absolute paths, URLs and
      `..` leave it. */
  function outsideFolder(path) {
    const p = String(path || '').trim();
    if (/^data:/i.test(p)) return false;
    return /^([a-z][a-z0-9+.-]*:|[\\/])/i.test(p) || /(^|[\\/])\.\.([\\/]|$)/.test(p);
  }

  function checkInsideFolder(kind, path, where) {
    if (outsideFolder(path)) {
      warn(`${kind} "${path}" points outside the presentation folder; it will be missing once the folder is copied or zipped (keep files in images/ or next to the deck)`, where);
    }
  }

  function fileName(path) {
    return String(path).split(/[?#]/)[0].split(/[\\/]/).pop() || String(path);
  }

  function escapeXml(text) {
    return text.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[c]);
  }

  /** White box with a grey border and a one-line label (scales with the box), as SVG data URI. */
  function placeholderSvg(kind, path, width, height) {
    const W = Math.max(1, Math.round(width)), H = Math.max(1, Math.round(height));
    const label = `${kind} "${fileName(path)}" not found`;
    const fs = Math.max(4, Math.min(0.8 * W / (label.length * 0.56), H / 3));   // ~80 % of the width
    const fit = label.length * fs * 0.56 > W * 0.9
      ? ` textLength="${(W * 0.9).toFixed(1)}" lengthAdjust="spacingAndGlyphs"` : '';
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
      `<filter id="g"><feColorMatrix type="saturate" values="0"/></filter>` +   // grey label, no LCD colour fringes
      `<rect x="1" y="1" width="${W - 2}" height="${H - 2}" fill="#fff" stroke="#c9c9c9" stroke-width="2" vector-effect="non-scaling-stroke"/>` +
      `<text x="50%" y="50%" text-anchor="middle" dominant-baseline="central" fill="#888" filter="url(#g)" ` +
      `font-family="Inter, 'Segoe UI', system-ui, sans-serif" font-size="${fs.toFixed(1)}"${fit}>${escapeXml(label)}</text></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  // Image sizes seen while an image loaded are remembered in this browser (localStorage, per deck
  // file), so a missing image without width/height attributes still gets its real size (R7-1).
  const SIZE_KEY = 'deck-image-sizes:' + location.pathname;

  function sizeMemory() {
    try { return JSON.parse(localStorage.getItem(SIZE_KEY) || '{}') || {}; } catch (e) { return {}; }
  }

  function rememberSize(src, width, height) {
    if (!(width > 0 && height > 0)) return;
    try {
      const sizes = sizeMemory();
      const old = sizes[src];
      if (old && old[0] === width && old[1] === height) return;
      sizes[src] = [width, height];
      localStorage.setItem(SIZE_KEY, JSON.stringify(sizes));
    } catch (e) { /* storage unavailable (private mode, blocked): nothing to remember */ }
  }

  function missingImage(img) {
    if (img.hasAttribute('data-asset-missing')) return;
    const src = img.getAttribute('src');
    let W = Number(img.getAttribute('width')), H = Number(img.getAttribute('height'));
    if (!(W > 0 && H > 0)) {
      const remembered = sizeMemory()[src];
      if (remembered) [W, H] = remembered;
      else {
        // Real size unknown (already warned): fill the parent's width at 16:9.
        W = (img.parentElement && img.parentElement.clientWidth) || 640;
        H = W * 9 / 16;
      }
    }
    img.setAttribute('data-asset-missing', src);
    img.classList.add('asset-missing');
    img.src = placeholderSvg('image', src, W, H);
    warn(`image "${fileName(src)}" not found (${src})`, { el: img });
  }

  function initImages(root) {
    for (const img of root.querySelectorAll('img')) {
      const src = img.getAttribute('src');
      if (!src) { warn('<img> without src', { el: img }); continue; }
      if (/^data:/i.test(src)) continue;
      checkInsideFolder('image', src, { el: img });
      if (!(img.hasAttribute('width') && img.hasAttribute('height'))) {
        warn(`image "${fileName(src)}" has no width/height attributes (its natural pixel size); if the file goes missing, only a size remembered by this browser can keep the placeholder's size`, { el: img });
      }
      // Errors may already have happened while the page was parsed, before this script ran.
      const loaded = () => {   // never remember the placeholder's own (guessed) size
        if (!img.hasAttribute('data-asset-missing')) rememberSize(src, img.naturalWidth, img.naturalHeight);
      };
      if (img.complete) { if (img.naturalWidth) loaded(); else missingImage(img); }
      else {
        img.addEventListener('error', () => missingImage(img), { once: true });
        img.addEventListener('load', loaded, { once: true });
      }
    }
  }

  function markBackgroundMissing(el, path) {
    const W = el.offsetWidth || cfg.canvas.width, H = el.offsetHeight || cfg.canvas.height;
    el.classList.add('asset-missing');
    el.setAttribute('data-asset-missing', path);
    Object.assign(el.style, {
      backgroundImage: `url("${placeholderSvg('image', path, W, H)}")`,
      backgroundSize: '100% 100%', backgroundPosition: '0 0', backgroundRepeat: 'no-repeat',
    });
    const slide = slides[slideIndexOf(el)];
    if (slide && slide.type === 'title') {
      slide.el.classList.add('cover-missing');
      if (state.current === slide.index) updateLetterbox();
    }
    warn(`image "${fileName(path)}" not found (${path})`, { el });
  }

  function initBackgrounds(root) {
    for (const el of root.querySelectorAll('[data-bg]')) {
      const path = el.dataset.bg;
      checkInsideFolder('image', path, { el });
      const probe = new Image();
      probe.onload = () => {
        el.style.backgroundImage = `url(${JSON.stringify(path)})`;
        if (el.dataset.bgSize) el.style.backgroundSize = el.dataset.bgSize;
        if (el.dataset.bgPosition) el.style.backgroundPosition = el.dataset.bgPosition;
      };
      probe.onerror = () => markBackgroundMissing(el, path);
      probe.src = path;
    }
  }

  /** CSS url(...) images cannot be checked for existence: point authors to <img> / data-bg. */
  function checkCssUrls() {
    const userCss = document.getElementById('deck-user-styles');
    if (userCss && ABS_URL_RE.test(userCss.textContent)) {
      warn('user CSS loads images with url(...); a missing file cannot be detected there — use <img> or data-bg');
    }
    for (const el of document.querySelectorAll('#deck [style*="url("]')) {
      if (ABS_URL_RE.test(el.getAttribute('style'))) {
        warn('inline style loads an image with url(...); use data-bg="…" so a missing file shows a placeholder', { el });
      }
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
        hook(step, slide.el, { preview: PREVIEW, first: !slide.rendered, N: slide.N });
      } catch (err) {
        warn(`DECK.hooks["${slide.id}"] threw: ${err && err.message ? err.message : err}`, { slide: slide.index, step });
      }
    }
    slide.rendered = true;
  }

  function show(index, how) {
    const slide = slides[index];
    if (!slide.visited) {
      slide.step = how === 'back' ? slide.N - 1 : 0;
      slide.visited = true;
    }
    const previous = slides[state.current];
    if (previous && previous !== slide) {
      // Keys forwarded from a focused animation iframe moved us on: give focus back to the deck.
      if (previous.el.contains(document.activeElement)) releaseFocus();
      previous.el.classList.remove('is-active');
      previous.el.inert = true;
    }
    state.current = index;
    slide.el.classList.add('is-active');
    slide.el.inert = false;
    renderSlide(slide);
    updateLetterbox();
    refreshPanels();
  }

  function next() {
    if (isBlocked()) return false;
    const slide = slides[state.current];
    if (slide.step < slide.N - 1) { slide.step++; renderSlide(slide); return true; }
    if (state.current < slides.length - 1) { show(state.current + 1, 'forward'); return true; }
    return false;
  }

  function prev() {
    if (isBlocked()) return false;
    const slide = slides[state.current];
    if (slide.step > 0) { slide.step--; renderSlide(slide); return true; }
    if (state.current > 0) { show(state.current - 1, 'back'); return true; }
    return false;
  }

  function resolveIndex(target) {
    if (typeof target === 'string') {
      const byId = slides.findIndex(s => s.id === target);
      if (byId >= 0) return byId;
      if (/^\d+$/.test(target)) return Number(target);
      return -1;
    }
    return target;
  }

  /** Jump to a slide by 0-based index or by id; optionally set its step (0-based, clamped to 0…N-1). */
  function goTo(target, step) {
    const index = resolveIndex(target);
    if (!Number.isInteger(index) || index < 0 || index >= slides.length) {
      warn(`Deck.goTo: no slide ${JSON.stringify(target)}`);
      return false;
    }
    if (step !== undefined) {
      const slide = slides[index];
      slide.step = Math.min(slide.N - 1, Math.max(0, Math.round(Number(step)) || 0));
      slide.visited = true;
    }
    show(index, 'jump');
    return true;
  }

  // ── Overlays (☰ Slides navigator now, the animation picker in P4) ─────────
  // One overlay is open at a time. While open, forward/back are ignored (SPEC §8.4).

  const overlays = [];
  let openOverlay = null;

  function createOverlay(id, heading, onOpen) {
    const overlay = h('div', 'deck-overlay');
    overlay.id = id;
    const panel = h('div', 'deck-panel');
    const list = h('div', 'deck-panel-list');
    panel.append(h('h3', 'deck-panel-title', heading), list);
    overlay.appendChild(panel);
    const o = { id, overlay, panel, list, onOpen };
    overlay.addEventListener('click', e => { if (e.target === overlay) closeOverlay(o); });
    stage.appendChild(overlay);
    overlays.push(o);
    return o;
  }

  function openOverlayPanel(o) {
    if (openOverlay && openOverlay !== o) closeOverlay(openOverlay);
    if (o.onOpen) o.onOpen(o);
    o.overlay.classList.add('open');
    openOverlay = o;
    state.locked = true;
  }

  function closeOverlay(o) {
    o.overlay.classList.remove('open');
    if (openOverlay === o) { openOverlay = null; state.locked = false; }
    releaseFocus();
  }

  /** Move keyboard focus back to the deck (out of buttons and animation iframes). */
  function releaseFocus() {
    if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    window.focus();
  }

  function toggleOverlay(o) {
    if (openOverlay === o) closeOverlay(o); else openOverlayPanel(o);
  }

  function refreshPanels() {
    for (const o of overlays) {
      for (const row of o.list.querySelectorAll('.deck-row[data-slide]')) {
        row.classList.toggle('is-current', Number(row.dataset.slide) === state.current);
      }
    }
  }

  // ── Thumbnails (SPEC §11): iframes of this deck in ?preview mode, loaded one by one ──

  const thumbCache = new Map();
  const thumbQueue = [];
  let thumbLoading = false;

  function previewUrl(index) {
    return location.href.split(/[?#]/)[0] + '?preview=' + index;
  }

  /** Queue an iframe; queued frames load one after another (SPEC §11). */
  function enqueueFrame(frame, url, onStart) {
    frame.dataset.src = url;
    thumbQueue.push({ frame, onStart });
    pumpThumbs();
  }

  function pumpThumbs() {
    if (thumbLoading) return;
    const item = thumbQueue.shift();
    if (!item) return;
    thumbLoading = true;
    let finished = false;
    const done = () => { if (finished) return; finished = true; thumbLoading = false; pumpThumbs(); };
    item.frame.addEventListener('load', done, { once: true });
    setTimeout(done, QUEUE_STEP_MS);
    item.frame.src = item.frame.dataset.src;
    if (item.onStart) item.onStart();
  }

  /** Start a queued frame right away (e.g. an animation opened before its turn came). */
  function startNow(frame) {
    const i = thumbQueue.findIndex(item => item.frame === frame);
    if (i < 0) return;
    const [item] = thumbQueue.splice(i, 1);
    item.frame.src = item.frame.dataset.src;
    if (item.onStart) item.onStart();
  }

  function thumbnail(index, cacheKey = index) {
    if (thumbCache.has(cacheKey)) return thumbCache.get(cacheKey);
    const { width: W, height: H } = cfg.canvas;
    const box = h('div', 'deck-thumb');
    box.style.width = THUMB_WIDTH + 'px';
    box.style.height = (THUMB_WIDTH * H / W) + 'px';
    const frame = document.createElement('iframe');
    frame.tabIndex = -1;
    frame.setAttribute('aria-hidden', 'true');
    frame.style.width = W + 'px';
    frame.style.height = H + 'px';
    frame.style.transform = `scale(${THUMB_WIDTH / W})`;
    box.appendChild(frame);
    thumbCache.set(cacheKey, box);
    enqueueFrame(frame, previewUrl(index));
    return box;
  }

  function slideNumberText(slide) {
    if (slide.type === 'black') return '–';
    return slide.zone === 'appendix' ? slide.label : `Slide ${slide.label}`;
  }

  // ── Animations (SPEC §9) ──────────────────────────────────────────────────
  // Every animation iframe (on a slide, behind the ▶ button, or as picker thumbnail) is an
  // independent instance. An instance counts as present only after the animation's contract
  // snippet answered with `ready`; otherwise it is replaced by the placeholder (SPEC §9.5, §10.4).

  const animFrames = [];               // { anim, kind: 'slide'|'overlay'|'thumb', frame, box, slide, ready, missing }
  const overlayInstances = new Map();  // anim id → instance shown by the ▶ button / picker
  let animOverlay = null, animButton = null, picker = null;
  const pickerRows = [];

  function animUrl(anim, params, thumb) {
    const extra = String(params || '').replace(/^[?&]+/, '');
    return `${anim.file}?deck-embed=1${thumb ? '&deck-thumb=1' : ''}${extra ? '&' + extra : ''}`;
  }

  function postToFrame(frame, message) {
    if (frame.contentWindow) frame.contentWindow.postMessage({ ns: 'deck', v: 1, ...message }, '*');
  }

  /** opts: { params, slide, queue, missingName, thumb } */
  function createAnimFrame(anim, kind, opts = {}) {
    const box = h('div', `anim-box anim-box--${kind}`);
    const frame = document.createElement('iframe');
    frame.className = 'anim-frame';
    frame.setAttribute('allow', 'fullscreen');
    if (kind === 'thumb') { frame.tabIndex = -1; frame.setAttribute('aria-hidden', 'true'); }
    box.appendChild(frame);
    const rec = { anim, kind, frame, box, slide: opts.slide ?? null, ready: false, missing: false,
                  missingName: opts.missingName };
    animFrames.push(rec);
    if (!anim) { markAnimMissing(rec); return rec; }

    const checkLater = ms => setTimeout(() => { if (!rec.ready) markAnimMissing(rec); }, ms);
    frame.addEventListener('load', () => {
      if (rec.ready || rec.missing) return;
      postToFrame(frame, { type: 'ping' });    // race-free backup for an early `ready`
      checkLater(ANIM_READY_MS);
    });
    const url = animUrl(anim, opts.params, kind === 'thumb');
    if (opts.queue) enqueueFrame(frame, url, () => checkLater(ANIM_TOTAL_MS));
    else { frame.src = url; checkLater(ANIM_TOTAL_MS); }
    return rec;
  }

  function markAnimMissing(rec) {
    if (rec.missing || rec.ready) return;
    rec.missing = true;
    const file = rec.anim ? rec.anim.file : rec.missingName;
    const placeholder = h('div', 'anim-missing');
    placeholder.style.cssText = rec.frame.style.cssText;   // thumbnails keep their scaled frame geometry
    placeholder.style.backgroundImage = `url("${placeholderSvg('animation', file, cfg.canvas.width, cfg.canvas.height)}")`;
    placeholder.setAttribute('data-asset-missing', file);
    rec.frame.replaceWith(placeholder);
    rec.placeholder = placeholder;
    if (!rec.anim) return;   // unknown id: already reported for its slide
    const detail = `animation "${fileName(file)}" not found (DECK.animations "${rec.anim.id}" → ${file})`;
    if (rec.kind === 'slide') warn(detail, { slide: rec.slide });
    else if (rec.kind === 'overlay') warn(detail);
  }

  function onAnimMessage(e) {
    const rec = animFrames.find(r => !r.missing && r.frame.contentWindow === e.source);
    if (!rec) return;
    const data = e.data;
    if (!data || typeof data !== 'object') return;
    const legacyKey = data.ns === undefined && data.type === 'keydown' && typeof data.key === 'string';
    if (data.ns !== 'deck' && !legacyKey) return;
    if (data.type === 'ready') { rec.ready = true; return; }
    if (data.type !== 'key' && !legacyKey) return;
    // Only the animation on the current slide navigates; overlay and thumbnail instances never do.
    if (rec.kind !== 'slide' || rec.slide !== state.current || isBlocked()) return;
    if (FORWARD_KEYS.has(data.key)) next();
    else if (BACK_KEYS.has(data.key)) prev();
  }

  function buildAnimations() {
    if (!anims.length) return;
    animOverlay = h('div');
    animOverlay.id = 'anim-overlay';
    stage.appendChild(animOverlay);
    for (const anim of anims) {   // loaded at startup, one after another (decision R8-3)
      const rec = createAnimFrame(anim, 'overlay', { queue: true });
      animOverlay.appendChild(rec.box);
      overlayInstances.set(anim.id, rec);
    }
    animButton = h('button', 'top-btn');
    animButton.id = 'anim-btn';
    animButton.type = 'button';
    animButton.addEventListener('click', () => {
      if (anims.length === 1) { if (state.animOpen) closeAnimation(); else openAnimation(anims[0].id); }
      else toggleOverlay(picker);
    });
    topbar.prepend(animButton);   // [▶ Animation] [☰ Slides]
    if (anims.length > 1) buildPicker();
    updateAnimButton();
  }

  function buildPicker() {
    picker = createOverlay('anim-picker', 'Animations', () => refreshPicker());
    const presentation = h('div', 'deck-row');
    presentation.dataset.anim = '';
    const info = h('div', 'row-info');
    info.append(h('div', 'row-num', 'Presentation'), h('div', 'row-label', slides[0] ? slides[0].title : ''));
    presentation.append(slides.length ? thumbnail(0, 'picker') : h('div', 'deck-thumb'), info);
    pickerRows.push(presentation);
    for (const anim of anims) {
      const row = h('div', 'deck-row');
      row.dataset.anim = anim.id;
      const { width: W, height: H } = cfg.canvas;
      const thumb = h('div', 'deck-thumb');
      thumb.style.width = THUMB_WIDTH + 'px';
      thumb.style.height = (THUMB_WIDTH * H / W) + 'px';
      const rec = createAnimFrame(anim, 'thumb', { queue: true });
      Object.assign(rec.frame.style, { width: W + 'px', height: H + 'px', transform: `scale(${THUMB_WIDTH / W})` });
      thumb.appendChild(rec.box);
      const rowInfo = h('div', 'row-info');
      rowInfo.append(h('div', 'row-num', 'Animation'), h('div', 'row-label', anim.name), h('div', 'row-sub', fileName(anim.file)));
      row.append(thumb, rowInfo);
      pickerRows.push(row);
    }
    for (const row of pickerRows) {
      row.addEventListener('click', () => {
        closeOverlay(picker);
        if (row.dataset.anim) openAnimation(row.dataset.anim); else closeAnimation();
      });
      picker.list.appendChild(row);
    }
  }

  function refreshPicker() {
    for (const row of pickerRows) row.classList.toggle('is-current', row.dataset.anim === (state.animOpen || ''));
  }

  function updateAnimButton() {
    if (!animButton) return;
    const open = state.animOpen !== null;
    animButton.textContent = anims.length === 1
      ? (open ? '◀ Presentation' : '▶ Animation')
      : (open ? '⇄ Switch' : '▶ Animations');
  }

  function openAnimation(id) {
    const rec = overlayInstances.get(id);
    if (!rec) { warn(`Deck.openAnimation: no animation "${id}"`); return false; }
    if (openOverlay) closeOverlay(openOverlay);
    startNow(rec.frame);
    for (const other of overlayInstances.values()) other.box.classList.toggle('is-active', other === rec);
    animOverlay.classList.add('open');
    state.animOpen = id;
    updateAnimButton();
    refreshPicker();
    return true;
  }

  function closeAnimation() {
    if (!animOverlay || state.animOpen === null) return false;
    animOverlay.classList.remove('open');   // instances stay loaded: their state is kept
    state.animOpen = null;
    releaseFocus();
    updateAnimButton();
    refreshPicker();
    return true;
  }

  // ── Top bar, ☰ Slides navigator, dev problems (SPEC §12.5, §12.6; R6-1…R6-4) ──
  // One navigator for everything: with ?dev it additionally lists every slide's problems,
  // a red "Deck" box for deck-wide problems, and the ☰ button turns red.

  let navButton = null, nav = null, navDeckBox = null, badge = null;
  const navRows = [];

  function buildTopbar() {
    topbar = h('div');
    topbar.id = 'deck-topbar';
    stage.appendChild(topbar);
  }

  function buildNavigator() {
    nav = createOverlay('nav-overlay', 'All Slides', renderNav);
    navDeckBox = h('div', 'nav-deck-problems');
    navDeckBox.hidden = true;
    nav.panel.insertBefore(navDeckBox, nav.list);
    for (const slide of slides) {
      const row = h('div', 'deck-row');
      row.dataset.slide = slide.index;
      const info = h('div', 'row-info');
      info.append(h('div', 'row-num', slideNumberText(slide)), h('div', 'row-label', slide.title));
      row.append(thumbnail(slide.index), info);   // thumbnails load one after another
      row.addEventListener('click', () => {
        closeOverlay(nav);
        closeAnimation();   // jumping means: back to the presentation (R8-2)
        goTo(slide.index, stepFor(slide.index));
      });
      nav.list.appendChild(row);
      navRows.push(row);
    }
    navButton = h('button', 'top-btn', '☰ Slides');
    navButton.id = 'nav-btn';
    navButton.type = 'button';
    navButton.addEventListener('click', () => toggleOverlay(nav));
    topbar.appendChild(navButton);   // the animation button sits to its left
    refreshDevUi();
  }

  function slideProblems(index) {
    return problems.filter(p => p.slide === index)
      .map(p => ({ ...p, at: problemStep(p) }))
      .sort((x, y) => x.at - y.at);
  }

  /** R6-4: with ?dev, a slide with problems opens at the first step that shows one;
      otherwise step memory applies (undefined = let goTo restore/start the slide). */
  function stepFor(index) {
    if (!DEV) return undefined;
    const list = slideProblems(index);
    return list.length ? Math.min(list[0].at, slides[index].N - 1) : undefined;
  }

  function revealRow(panel, row) {
    const top = row.offsetTop, bottom = top + row.offsetHeight;
    if (top < panel.scrollTop) panel.scrollTop = top - 12;
    else if (bottom > panel.scrollTop + panel.clientHeight) panel.scrollTop = bottom - panel.clientHeight + 12;
  }

  function renderNav() {
    refreshPanels();
    if (DEV) renderNavProblems();
    const row = navRows[state.current];
    if (row) revealRow(nav.panel, row);
  }

  function renderNavProblems() {
    const deckWide = problems.filter(p => p.slide === null);
    navDeckBox.hidden = !deckWide.length;
    const deckList = h('ul', 'row-problems');
    deckWide.forEach(p => deckList.appendChild(h('li', '', p.message)));
    navDeckBox.replaceChildren(h('div', 'row-num', 'Deck'), deckList);
    for (const row of navRows) {
      const list = slideProblems(Number(row.dataset.slide));
      const info = row.querySelector('.row-info');
      const old = info.querySelector('.row-problems');
      if (old) old.remove();
      row.classList.toggle('has-problems', list.length > 0);
      if (list.length) {
        const ul = h('ul', 'row-problems');
        list.forEach(p => ul.appendChild(h('li', '', `step ${p.at} · ${p.message}`)));
        info.appendChild(ul);
      }
    }
  }

  function buildBadge() {
    badge = h('div');
    badge.id = 'deck-warnings';
    const toggle = h('button', 'dw-toggle');
    const close = h('button', 'dw-close', '×');
    close.title = 'Hide (reload to show again)';
    toggle.addEventListener('click', () => badge.classList.toggle('open'));
    close.addEventListener('click', () => badge.remove());
    badge.append(toggle, close, h('ol', 'dw-list'));
    document.body.appendChild(badge);
    refreshDevUi();
  }

  function refreshDevUi() {
    if (!DEV) return;
    const n = warnings.length;
    if (navButton) navButton.classList.toggle('has-problems', n > 0);
    if (badge) {
      badge.className = (n ? 'has-warnings' : 'no-warnings') + (badge.classList.contains('open') ? ' open' : '');
      badge.querySelector('.dw-toggle').textContent = n ? `⚠ ${n} deck warning${n === 1 ? '' : 's'}` : '✓ no deck warnings';
      badge.querySelector('.dw-list').replaceChildren(...warnings.map(w => h('li', '', w)));
    }
    if (nav && openOverlay === nav) renderNavProblems();
  }

  function buildHint() {
    const hint = h('div', '', '← → to navigate');
    hint.id = 'deck-hint';
    stage.appendChild(hint);
    setTimeout(() => hint.classList.add('faded'), HINT_MS);
  }

  // ── Input (SPEC §8.4, decision R4-4) ──────────────────────────────────────

  function isEditable(target) {
    return target instanceof Element &&
      (target.isContentEditable || !!target.closest('input, textarea, select, [contenteditable]'));
  }

  function onKeyDown(e) {
    if (e.defaultPrevented || e.altKey || e.metaKey || isEditable(e.target)) return;
    if (e.key === 'Escape' && openOverlay) {
      e.preventDefault();
      closeOverlay(openOverlay);
      return;
    }
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

  // ── Code highlighting (SPEC §14): <pre class="code-block" data-lang="python"> ──
  // Hand-coloured blocks (containing token spans) are left alone.

  const PY_KEYWORDS = new Set(('False None True and as assert async await break class continue def del elif ' +
    'else except finally for from global if import in is lambda nonlocal not or pass raise return try ' +
    'while with yield self cls').split(' '));
  const PY_TOKEN = /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?j?\b)|([A-Za-z_]\w*)|([\s\S])/g;
  const PY_AFTER = /\s*(\(|=(?!=))?/y;

  function escapeHtml(text) {
    return text.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
  }

  function highlightPython(src) {
    let out = '', depth = 0, m;
    PY_TOKEN.lastIndex = 0;
    while ((m = PY_TOKEN.exec(src))) {
      const [tok, comment, str, num, ident] = m;
      const span = cls => `<span class="${cls}">${escapeHtml(tok)}</span>`;
      if (comment) out += span('cc');
      else if (str) out += span('cs');
      else if (num) out += span('cn');
      else if (ident) {
        PY_AFTER.lastIndex = PY_TOKEN.lastIndex;
        const next = PY_AFTER.exec(src)[1];
        if (PY_KEYWORDS.has(ident)) out += span('ck');
        else if (next === '(') out += span('cf');
        else if (next && depth > 0) out += span('ca');   // keyword argument inside a call
        else out += escapeHtml(tok);
      } else {
        if ('([{'.includes(tok)) depth++;
        else if (')]}'.includes(tok)) depth = Math.max(0, depth - 1);
        out += escapeHtml(tok);
      }
    }
    return out;
  }

  function highlightCode(root, quiet) {
    for (const el of root.querySelectorAll('[data-lang]')) {
      const lang = el.dataset.lang.toLowerCase();
      if (lang !== 'python' && lang !== 'py') {
        if (!quiet) warn(`code language "${lang}" is not coloured automatically (only python); use the token classes .ck .cf .ca .cn .cs .cc`, { el });
        continue;
      }
      if (el.children.length) continue;
      el.innerHTML = highlightPython(el.textContent);
    }
  }

  // ── Sample image for component previews ──────────────────────────────────

  /** Neutral stand-in image for component previews (the snippets' image paths are examples). */
  function sampleImageSvg(width, height) {
    const W = Math.max(1, Math.round(width)), H = Math.max(1, Math.round(height));
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">` +
      `<rect width="${W}" height="${H}" fill="#e9edf3"/><path d="M0 ${H} L${W * 0.35} ${H * 0.45} L${W * 0.6} ${H * 0.75} L${W * 0.78} ${H * 0.55} L${W} ${H}Z" fill="#c9d3e1"/></svg>`;
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  // ── ?dev "Components" button + panel (SPEC §12.8, decision R11-1) ────────
  // A catalog of the built-in components, so slides reuse them instead of inventing new ones.
  // Each entry: title, origin, a live example scaled to the panel width, and its HTML (folded).

  let compPanel = null, compButton = null;

  function buildComponentsPanel() {
    compPanel = createOverlay('comp-overlay', 'Components', () => {
      if (!compPanel.list.childElementCount) renderComponentList(compPanel.list);
    });
    compPanel.panel.classList.add('wide');
    compPanel.list.classList.add('comp-list');
    compButton = h('button', 'top-btn', '▦ Components');
    compButton.id = 'comp-btn';
    compButton.type = 'button';
    compButton.addEventListener('click', () => toggleOverlay(compPanel));
    topbar.insertBefore(compButton, navButton);   // [▶ Animation] [▦ Components] [☰ Slides]
  }

  function renderComponentList(list) {
    // Examples are laid out at the real content width of a slide, then scaled to the panel.
    const stageWidth = cfg.canvas.width - 2 * 63 + 2 * 22.5;
    for (const c of COMPONENTS) {
      const item = h('div', 'comp-item');
      const preview = h('div', 'comp-preview');
      const stage = h('div', 'slide-content comp-stage');
      stage.style.width = stageWidth + 'px';
      if (c.height) stage.style.height = c.height + 'px';
      stage.innerHTML = c.html;
      for (const img of stage.querySelectorAll('img')) {
        img.src = sampleImageSvg(Number(img.getAttribute('width')) || 1600, Number(img.getAttribute('height')) || 900);
      }
      for (const el of stage.querySelectorAll('[data-bg]')) {
        el.style.backgroundImage = `url("${sampleImageSvg(400, 300)}")`;
        el.style.backgroundSize = '100% 100%';
      }
      for (const el of stage.querySelectorAll('[data-step-class]')) {   // show the final state:
        for (const rule of el.dataset.stepClass.trim().split(/\s+/)) {    // open-ended class rules on
          const cut = rule.lastIndexOf(':');
          if (cut > 0 && !rule.includes('..')) el.classList.add(rule.slice(0, cut));
        }
      }
      highlightCode(stage, true);
      if (typeof window.renderMathInElement === 'function') {
        protectDollars(stage);
        window.renderMathInElement(stage, { delimiters: MATH_DELIMITERS, throwOnError: false });
        restoreDollars(stage);
      }
      preview.appendChild(stage);

      const code = document.createElement('details');
      code.className = 'comp-code';
      const summary = h('summary', '', 'HTML');
      const copy = h('button', 'comp-copy', 'Copy');
      copy.type = 'button';
      copy.addEventListener('click', () => copyText(c.html.trim(), copy));
      code.append(summary, copy, h('pre', '', c.html.trim()));

      item.append(h('div', 'comp-title', c.name), h('div', 'comp-from', 'from: ' + c.from), preview, code);
      list.appendChild(item);
    }
    // Measure after all items exist (the panel's scrollbar changes the available width). The
    // panel is laid out (only transparent) while it opens, so the examples can be measured.
    for (const preview of list.querySelectorAll('.comp-preview')) {
      const stage = preview.firstElementChild;
      const scale = preview.clientWidth / stageWidth;
      stage.style.transform = `scale(${scale})`;
      preview.style.height = Math.ceil(stage.offsetHeight * scale) + 'px';
    }
  }

  function copyText(text, button) {
    const label = button.textContent;
    const done = ok => {
      button.textContent = ok ? 'Copied ✓' : 'Copy failed';
      setTimeout(() => { button.textContent = label; }, 1500);
    };
    const fallback = () => {
      const area = h('textarea');
      area.value = text;
      area.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(area);
      area.select();
      let ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      area.remove();
      done(ok);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(() => done(true), fallback);
    else fallback();
  }

  // ── Math ──────────────────────────────────────────────────────────────────

  /** `\$` outside of formulas means a literal dollar sign (SPEC §13). Inside formulas `\$` is TeX
      and stays untouched. */
  function escapeDollarsOutsideMath(text) {
    let out = '', i = 0, end = null;
    while (i < text.length) {
      if (end) {                                    // inside a formula
        if (text[i] === '\\') { out += text.slice(i, i + 2); i += 2; continue; }
        if (text.startsWith(end, i)) { out += end; i += end.length; end = null; continue; }
        out += text[i++];
        continue;
      }
      if (text.startsWith('\\$', i)) { out += DOLLAR; i += 2; continue; }
      const open = ['$$', '$', '\\(', '\\['].find(d => text.startsWith(d, i));
      if (open) { end = { '$$': '$$', '$': '$', '\\(': '\\)', '\\[': '\\]' }[open]; out += open; i += open.length; continue; }
      out += text[i++];
    }
    return out;
  }

  function textNodes(root, skipSelector) {
    const nodes = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!skipSelector || !(n.parentElement && n.parentElement.closest(skipSelector))) nodes.push(n);
    }
    return nodes;
  }

  function protectDollars(root) {
    for (const n of textNodes(root, MATH_IGNORE)) if (n.data.includes('\\$')) n.data = escapeDollarsOutsideMath(n.data);
  }

  function restoreDollars(root) {
    for (const n of textNodes(root)) if (n.data.includes(DOLLAR)) n.data = n.data.split(DOLLAR).join('$');
  }

  function renderMath() {
    if (typeof window.renderMathInElement !== 'function') {
      warn('KaTeX auto-render is not available; formulas stay as source text');
      return;
    }
    // Rendered per slide so formula problems are attributed to their slide. With
    // throwOnError:false KaTeX shows unknown commands in red instead of failing, so each
    // formula is also parsed strictly: one that parses in neither mode is reported, and the
    // rendered element is looked up afterwards (via its TeX annotation) to know its step.
    for (const slide of slides) {
      const failing = [];
      const check = math => {
        let error;
        for (const displayMode of [false, true]) {
          try { window.katex.renderToString(math, { displayMode, throwOnError: true }); return math; }
          catch (err) { error = err; }
        }
        failing.push({ math, error });
        return math;
      };
      protectDollars(slide.el);
      window.renderMathInElement(slide.el, {
        delimiters: MATH_DELIMITERS,
        throwOnError: false,
        preProcess: check,
        errorCallback: (message, err) => warn(`formula error: ${message} ${err || ''}`.trim(), { slide: slide.index }),
      });
      restoreDollars(slide.el);
      const rendered = [...slide.el.querySelectorAll('.katex, .katex-error')];
      const source = k => {
        const ann = k.querySelector('annotation[encoding="application/x-tex"]');
        return (ann ? ann.textContent : k.textContent).trim();
      };
      for (const { math, error } of failing) {
        const i = rendered.findIndex(k => source(k) === math.trim());
        const el = i >= 0 ? rendered.splice(i, 1)[0] : undefined;
        warn(`formula error in "${math}": ${error && error.message ? error.message : error}`, { slide: slide.index, el });
      }
    }
  }

  // ── Boot (SPEC §17) ───────────────────────────────────────────────────────

  function summary(s) {
    return { index: s.index, id: s.id, type: s.type, zone: s.zone, label: s.label,
             title: s.title, N: s.N, step: s.step, visited: s.visited };
  }

  window.Deck = {
    version: VERSION,
    dev: DEV,
    preview: PREVIEW,
    warnings,
    get problems() { return problems.map(p => ({ message: p.message, slide: p.slide, step: problemStep(p) })); },
    get slides() { return slides.map(summary); },
    get state() {
      const s = slides[state.current];
      return { current: state.current, id: s && s.id, step: s && s.step, N: s && s.N,
               label: s && s.label, locked: state.locked, animOpen: state.animOpen, scale: state.scale };
    },
    get animations() {
      return anims.map(a => ({ ...a, instances: animFrames.filter(r => r.anim === a)
        .map(r => ({ kind: r.kind, slide: r.slide, ready: r.ready, missing: r.missing })) }));
    },
    next, prev, goTo,
    openAnimation: id => openAnimation(id),
    closeAnimation: () => closeAnimation(),
    fit: () => fit(),
  };

  function bootPreview() {
    // ?preview=<index or id>[&step=k]: render one slide at its final step (or k), nothing else.
    const target = resolveIndex(PARAMS.get('preview'));
    const index = Number.isInteger(target) && target >= 0 && target < slides.length ? target : 0;
    const slide = slides[index];
    const step = PARAMS.has('step') ? Number(PARAMS.get('step')) : slide.N - 1;
    goTo(index, step);
  }

  function boot() {
    const deckEl = document.getElementById('deck');
    if (PREVIEW) document.documentElement.classList.add('deck-preview');
    try {
      cfg = readConfig();
      if (!deckEl) throw new Error('no <main id="deck"> element found');
      buildCanvas(deckEl);
      window.addEventListener('message', onAnimMessage);   // before any animation iframe exists
      if (!PREVIEW) buildTopbar();
      if (DEV) buildBadge();
      parseSlides(deckEl);
      highlightCode(deckEl);
      checkCssUrls();
      initImages(deckEl);
      initBackgrounds(deckEl);
      renderMath();
      renderDates();
      fit();
      fitCoverBox();
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(fitCoverBox);
      window.addEventListener('resize', fit);
      slides.forEach(s => { s.el.inert = true; });
      if (!slides.length) warn('the deck has no slides');
      else if (PREVIEW) bootPreview();
      else {
        if (cfg.date === 'auto') scheduleMidnightRefresh();
        document.addEventListener('keydown', onKeyDown);
        show(0, 'forward');
        buildNavigator();
        if (DEV) buildComponentsPanel();
        buildAnimations();
        buildHint();
      }
    } catch (err) {
      warn(`engine failed to start: ${err && err.message ? err.message : err}`);
      console.error(err);
    } finally {
      document.documentElement.classList.remove('deck-loading');
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
