```js
const WORDMARK_URL = '/static/img/searchatlas-wordmark-white.svg';
const DEFAULT_DURATION = 3000;
const WORDMARK_FETCH_TIMEOUT = 2500;
const SVG_NS = 'http://www.w3.org/2000/svg';

let logoSerial = 0;

injectStyles();

function injectStyles() {
  if (document.getElementById('sa-preloader-styles')) return;

  const style = document.createElement('style');
  style.id = 'sa-preloader-styles';
  style.textContent = CSS;
  (document.head || document.documentElement).appendChild(style);
}

function delay(milliseconds) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

function bodyReady() {
  if (document.body) return Promise.resolve();

  return new Promise((resolve) => {
    document.addEventListener('DOMContentLoaded', resolve, { once: true });
  });
}

function prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

function createFallbackLogo() {
  const image = document.createElement('img');
  image.className = 'sa-preloader__logo';
  image.src = WORDMARK_URL;
  image.alt = 'Search Atlas';
  image.draggable = false;
  image.decoding = 'async';
  return image;
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS(SVG_NS, name);

  Object.entries(attributes).forEach(([attribute, value]) => {
    element.setAttribute(attribute, String(value));
  });

  return element;
}

function readViewBox(source) {
  const rawViewBox = source.getAttribute('viewBox');

  if (rawViewBox) {
    const values = rawViewBox.trim().split(/[\s,]+/).map(Number);

    if (
      values.length === 4 &&
      values.every(Number.isFinite) &&
      values[2] > 0 &&
      values[3] > 0
    ) {
      return {
        x: values[0],
        y: values[1],
        width: values[2],
        height: values[3],
      };
    }
  }

  const width = Number.parseFloat(source.getAttribute('width'));
  const height = Number.parseFloat(source.getAttribute('height'));

  if (Number.isFinite(width) && width > 0 &&
      Number.isFinite(height) && height > 0) {
    return { x: 0, y: 0, width, height };
  }

  return { x: 0, y: 0, width: 1426, height: 256 };
}

function copyPath(source) {
  const path = svgElement('path', {
    d: source.getAttribute('d') || '',
  });

  ['fill-rule', 'clip-rule'].forEach((attribute) => {
    const value = source.getAttribute(attribute);
    if (value) path.setAttribute(attribute, value);
  });

  // Preserve transforms on the path and any ancestor groups, without copying
  // scripts, styles, event handlers, or other source document content.
  const transforms = [];
  let node = source;

  while (node && node.localName !== 'svg') {
    const transform = node.getAttribute('transform');
    if (transform) transforms.unshift(transform);
    node = node.parentElement;
  }

  if (transforms.length) {
    path.setAttribute('transform', transforms.join(' '));
  }

  return path;
}

function createPathLayer(className, sourcePaths, traced = false) {
  const group = svgElement('g', { class: className });

  sourcePaths.forEach((sourcePath) => {
    const path = copyPath(sourcePath);

    if (traced) {
      // Normalizing every path makes the inherited dash animation work
      // consistently regardless of each path's actual geometric length.
      path.setAttribute('pathLength', '1');
    }

    group.appendChild(path);
  });

  return group;
}

function buildLayeredLogo(source, sourcePaths) {
  const viewBox = readViewBox(source);
  const serial = ++logoSerial;
  const gradientId = `sa-preloader-spectrum-${serial}`;
  const maskId = `sa-preloader-light-mask-${serial}`;

  const svg = svgElement('svg', {
    class: 'sa-preloader__logo',
    xmlns: SVG_NS,
    viewBox: `${viewBox.x} ${viewBox.y} ${viewBox.width} ${viewBox.height}`,
    width: viewBox.width,
    height: viewBox.height,
    preserveAspectRatio: 'xMidYMid meet',
    role: 'img',
    'aria-label': 'Search Atlas',
    focusable: 'false',
  });

  const defs = svgElement('defs');
  const gradient = svgElement('linearGradient', {
    id: gradientId,
    gradientUnits: 'userSpaceOnUse',
    x1: viewBox.x - 1426,
    y1: viewBox.y,
    x2: viewBox.x,
    y2: viewBox.y,
  });

  [
    ['0%', '#00FFD4', '0'],
    ['16%', '#00FFD4', '.9'],
    ['38%', '#AA85EC', '1'],
    ['54%', '#FFFFFF', '1'],
    ['70%', '#936BDA', '.95'],
    ['100%', '#936BDA', '0'],
  ].forEach(([offset, color, opacity]) => {
    gradient.appendChild(svgElement('stop', {
      offset,
      'stop-color': color,
      'stop-opacity': opacity,
    }));
  });

  const lightMask = svgElement('mask', {
    id: maskId,
    maskUnits: 'userSpaceOnUse',
    maskContentUnits: 'userSpaceOnUse',
    x: viewBox.x,
    y: viewBox.y,
    width: viewBox.width,
    height: viewBox.height,
  });
  lightMask.style.maskType = 'luminance';

  sourcePaths.forEach((sourcePath) => {
    const path = copyPath(sourcePath);
    path.setAttribute('fill', '#fff');
    path.setAttribute('stroke', 'none');
    lightMask.appendChild(path);
  });

  defs.append(gradient, lightMask);
  svg.appendChild(defs);
  svg.appendChild(createPathLayer('sa-preloader__ghost', sourcePaths));
  svg.appendChild(createPathLayer('sa-preloader__trace', sourcePaths, true));
  svg.appendChild(createPathLayer('sa-preloader__solid', sourcePaths));

  const light = svgElement('g', {
    class: 'sa-preloader__light',
    mask: `url(#${maskId})`,
  });
  const spectrum = svgElement('g', {
    class: 'sa-preloader__spectrum',
  });

  // The existing spectrum keyframes move this rectangle by 1426 user units,
  // taking it from just outside the wordmark to across its full width.
  spectrum.appendChild(svgElement('rect', {
    x: viewBox.x - 1426,
    y: viewBox.y,
    width: 1426,
    height: viewBox.height,
    fill: `url(#${gradientId})`,
  }));

  light.appendChild(spectrum);
  svg.appendChild(light);

  return svg;
}

async function fetchWordmark() {
  const controller = typeof AbortController === 'function'
    ? new AbortController()
    : null;
  const timeout = controller
    ? window.setTimeout(() => controller.abort(), WORDMARK_FETCH_TIMEOUT)
    : null;

  try {
    const options = { credentials: 'same-origin' };
    if (controller) options.signal = controller.signal;

    const response = await fetch(WORDMARK_URL, options);
    if (!response.ok) {
      throw new Error(`Wordmark request failed: ${response.status}`);
    }

    return await response.text();
  } finally {
    if (timeout !== null) window.clearTimeout(timeout);
  }
}

async function loadLayeredLogo() {
  try {
    const markup = await fetchWordmark();
    const documentNode = new DOMParser().parseFromString(
      markup,
      'image/svg+xml'
    );
    const source = documentNode.documentElement;

    if (
      !source ||
      source.localName !== 'svg' ||
      documentNode.getElementsByTagName('parsererror').length
    ) {
      throw new Error('Invalid wordmark SVG');
    }

    const sourcePaths = Array.from(
      documentNode.getElementsByTagName('path')
    ).filter((path) => path.getAttribute('d'));

    if (!sourcePaths.length) {
      throw new Error('Wordmark contains no paths');
    }

    return buildLayeredLogo(source, sourcePaths);
  } catch {
    // The caller already mounted a plain <img>, so a network, parsing, or
    // security failure never leaves the overlay without a logo.
    return null;
  }
}

function lockPage() {
  const body = document.body;
  const root = document.documentElement;
  const previous = {
    bodyOverflow: body.style.overflow,
    bodyPaddingRight: body.style.paddingRight,
    rootOverflow: root.style.overflow,
    ariaBusy: body.getAttribute('aria-busy'),
  };

  const scrollbarWidth = Math.max(
    0,
    window.innerWidth - root.clientWidth
  );

  if (scrollbarWidth > 0) {
    const currentPadding = Number.parseFloat(
      window.getComputedStyle(body).paddingRight
    ) || 0;
    body.style.paddingRight = `${currentPadding + scrollbarWidth}px`;
  }

  root.style.overflow = 'hidden';
  body.style.overflow = 'hidden';
  body.setAttribute('aria-busy', 'true');

  const preventTouchScroll = (event) => {
    if (event.cancelable) event.preventDefault();
  };

  document.addEventListener('touchmove', preventTouchScroll, {
    passive: false,
  });

  let restored = false;

  return () => {
    if (restored) return;
    restored = true;

    document.removeEventListener('touchmove', preventTouchScroll);
    root.style.overflow = previous.rootOverflow;
    body.style.overflow = previous.bodyOverflow;
    body.style.paddingRight = previous.bodyPaddingRight;

    if (previous.ariaBusy === null) {
      body.removeAttribute('aria-busy');
    } else {
      body.setAttribute('aria-busy', previous.ariaBusy);
    }
  };
}

function rememberPreloader() {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(Date.now()));
  } catch {
    // Storage can be unavailable in private browsing or locked-down frames.
    // Displaying the preloader is always safe, so writes fail open too.
  }
}

async function runPreloader(duration) {
  await bodyReady();
  injectStyles();

  const reducedMotion = prefersReducedMotion();
  const overlay = document.createElement('div');
  const stage = document.createElement('div');

  overlay.className = 'sa-preloader';
  if (reducedMotion) overlay.classList.add('sa-preloader--reduced');

  overlay.style.setProperty(
    '--sa-preloader-duration',
    `${duration}ms`
  );
  overlay.setAttribute('role', 'status');
  overlay.setAttribute('aria-live', 'polite');
  overlay.setAttribute('aria-atomic', 'true');
  overlay.setAttribute('aria-label', 'Loading Search Atlas');
  overlay.setAttribute('aria-hidden', 'false');

  stage.className = 'sa-preloader__stage';
  stage.appendChild(createFallbackLogo());
  overlay.appendChild(stage);

  const unlockPage = lockPage();

  try {
    document.body.appendChild(overlay);
    rememberPreloader();

    const layeredLogo = await loadLayeredLogo();
    if (layeredLogo) stage.replaceChildren(layeredLogo);

    await delay(reducedMotion ? REDUCED_DURATION : duration);

    // Remove the loading announcement before the visual fade. Reduced-motion
    // mode skips the fade entirely, so its static logo lasts exactly 800ms.
    overlay.setAttribute('aria-hidden', 'true');

    if (!reducedMotion) {
      overlay.classList.add('sa-preloader--leaving');
      await delay(FADE_DURATION);
    }
  } finally {
    overlay.setAttribute('aria-hidden', 'true');
    overlay.remove();
    unlockPage();
  }
}

/**
 * Display the preloader. Concurrent calls share the same Promise and never
 * create additional overlays.
 *
 * @param {{ duration?: number }} options
 * @returns {Promise<void>}
 */
export function showPreloader(options = {}) {
  if (activePromise) return activePromise;

  const requested = options && typeof options === 'object' &&
    options.duration !== undefined
    ? Number(options.duration)
    : DEFAULT_DURATION;
  const duration = Number.isFinite(requested)
    ? Math.max(0, requested)
    : DEFAULT_DURATION;

  activePromise = runPreloader(duration).then(
    () => {
      activePromise = null;
    },
    (error) => {
      activePromise = null;
      throw error;
    }
  );

  return activePromise;
}

function shouldAutoPlay() {
  try {
    const parameters = new URLSearchParams(window.location.search);
    if (parameters.get('preloader') === '1') return true;
  } catch {
    // A malformed location should not prevent the normal storage gate.
  }

  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === null) return true;

    const lastShown = Number(stored);
    const now = Date.now();

    if (
      !Number.isFinite(lastShown) ||
      lastShown <= 0 ||
      lastShown > now
    ) {
      return true;
    }

    return now - lastShown >= MAX_AGE;
  } catch {
    // Blocked or inaccessible storage fails open.
    return true;
  }
}

function autoPlay() {
  if (!shouldAutoPlay()) return;

  // Autoplay is best-effort; manual callers still receive any rejection.
  showPreloader().catch(() => {});
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', autoPlay, { once: true });
} else {
  autoPlay();
}
```