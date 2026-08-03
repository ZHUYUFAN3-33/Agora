/**
 * Custom fade scrollbars — native scrollbar pseudos cannot animate opacity.
 * Keeps layout gutter; thumb fades in (150ms) / out (300ms) per ANIMATION_GUIDE.
 */

const SCROLL_SEL =
  ".overflow-y-auto, .overflow-auto, .overflow-y-scroll, [data-fade-scrollbar]";

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
const HIDE_DELAY_MS = 800;

type State = {
  rail: HTMLDivElement;
  thumb: HTMLDivElement;
  hovering: boolean;
  hideTimer: number | null;
};

const states = new WeakMap<HTMLElement, State>();

function isScrollable(el: HTMLElement): boolean {
  return el.scrollHeight > el.clientHeight + 1;
}

function ensurePositioned(el: HTMLElement) {
  const pos = getComputedStyle(el).position;
  if (pos === "static") {
    el.style.position = "relative";
  }
}

function updateThumb(el: HTMLElement, state: State) {
  const { rail, thumb } = state;
  const sh = el.scrollHeight;
  const ch = el.clientHeight;
  // Keep rail pinned to the visible viewport of the scroll container
  rail.style.top = `${el.scrollTop}px`;
  rail.style.height = `${ch}px`;

  if (sh <= ch + 1) {
    rail.classList.remove("is-visible");
    thumb.style.height = "0px";
    return false;
  }

  const ratio = ch / sh;
  const thumbH = Math.max(28, Math.round(ratio * ch));
  const maxTop = Math.max(0, ch - thumbH);
  const top = maxTop * (el.scrollTop / Math.max(1, sh - ch));
  thumb.style.height = `${thumbH}px`;
  thumb.style.transform = `translateY(${top}px)`;
  return true;
}

function show(el: HTMLElement, state: State) {
  if (!updateThumb(el, state)) return;
  state.rail.classList.add("is-visible");
  if (state.hideTimer != null) {
    window.clearTimeout(state.hideTimer);
    state.hideTimer = null;
  }
}

function scheduleHide(el: HTMLElement, state: State) {
  if (state.hideTimer != null) window.clearTimeout(state.hideTimer);
  state.hideTimer = window.setTimeout(() => {
    state.hideTimer = null;
    if (!state.hovering) state.rail.classList.remove("is-visible");
  }, HIDE_DELAY_MS);
}

function enhance(el: HTMLElement) {
  if (states.has(el) || el.closest(".agora-sb")) return;

  ensurePositioned(el);

  const rail = document.createElement("div");
  rail.className = "agora-sb";
  rail.setAttribute("aria-hidden", "true");
  const thumb = document.createElement("div");
  thumb.className = "agora-sb-thumb";
  rail.appendChild(thumb);
  el.appendChild(rail);

  const state: State = { rail, thumb, hovering: false, hideTimer: null };
  states.set(el, state);

  const onScroll = () => {
    show(el, state);
    scheduleHide(el, state);
  };
  const onEnter = () => {
    state.hovering = true;
    if (isScrollable(el)) show(el, state);
  };
  const onLeave = () => {
    state.hovering = false;
    scheduleHide(el, state);
  };

  el.addEventListener("scroll", onScroll, { passive: true });
  el.addEventListener("mouseenter", onEnter);
  el.addEventListener("mouseleave", onLeave);

  const ro = new ResizeObserver(() => {
    if (state.rail.classList.contains("is-visible") || state.hovering) {
      updateThumb(el, state);
    }
  });
  ro.observe(el);

  // Initial measure (hidden until hover/scroll)
  updateThumb(el, state);
}

function scan(root: ParentNode = document) {
  root.querySelectorAll<HTMLElement>(SCROLL_SEL).forEach(enhance);
}

export function installFadeScrollbars() {
  if (typeof document === "undefined") return;
  scan();

  const mo = new MutationObserver((mutations) => {
    for (const m of mutations) {
      m.addedNodes.forEach((node) => {
        if (!(node instanceof HTMLElement)) return;
        if (node.matches?.(SCROLL_SEL)) enhance(node);
        scan(node);
      });
    }
  });
  mo.observe(document.documentElement, { childList: true, subtree: true });

  // Expose ease token for CSS parity (optional debug)
  document.documentElement.style.setProperty("--agora-sb-ease", EASE);
}
