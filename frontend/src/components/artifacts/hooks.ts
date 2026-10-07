import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { RefObject } from 'react';
import { cssVar } from '../../lib/theme';

/* ------------------------------------------------------------ element size */

export interface Size {
  width: number;
  height: number;
}

/** Observes an element's content box. Width/height are rounded to whole pixels. */
export function useElementSize<T extends HTMLElement>(): [RefObject<T | null>, Size] {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = (w: number, h: number) => {
      const width = Math.round(w);
      const height = Math.round(h);
      setSize((prev) => (prev.width === width && prev.height === height ? prev : { width, height }));
    };
    const rect = el.getBoundingClientRect();
    update(rect.width, rect.height);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box) update(box.width, box.height);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return [ref, size];
}

/* --------------------------------------------------------- text measuring */

let fontsVersion = 0;
const fontListeners = new Set<() => void>();
const widthCache = new Map<string, number>();
let ctx: CanvasRenderingContext2D | null | undefined;

if (typeof document !== 'undefined' && document.fonts) {
  const bump = () => {
    widthCache.clear();
    fontsVersion += 1;
    fontListeners.forEach((l) => l());
  };
  document.fonts.addEventListener?.('loadingdone', bump);
  document.fonts.ready.then(bump).catch(() => undefined);
}

function subscribeFonts(l: () => void) {
  fontListeners.add(l);
  return () => fontListeners.delete(l);
}

/** Changes whenever web fonts finish loading, so layouts that measure text re-run. */
export function useFontsVersion(): number {
  return useSyncExternalStore(subscribeFonts, () => fontsVersion, () => 0);
}

const stacks: Record<string, string> = {};

/** CSS font shorthand for a token family, e.g. font('ui', 12, 500). */
export function font(family: 'ui' | 'mono', size: number, weight = 400): string {
  const varName = family === 'ui' ? '--font-ui' : '--font-mono';
  if (!stacks[varName]) {
    const v = typeof document !== 'undefined' ? cssVar(varName) : '';
    stacks[varName] = v || (family === 'ui' ? 'system-ui, sans-serif' : 'ui-monospace, monospace');
  }
  return `${weight} ${size}px ${stacks[varName]}`;
}

export function measureText(text: string, fontSpec: string): number {
  const key = `${fontSpec}\u0000${text}`;
  const hit = widthCache.get(key);
  if (hit !== undefined) return hit;
  if (ctx === undefined) ctx = typeof document !== 'undefined' ? document.createElement('canvas').getContext('2d') : null;
  let w: number;
  if (ctx) {
    ctx.font = fontSpec;
    w = ctx.measureText(text).width;
  } else {
    const px = Number(/(\d+(?:\.\d+)?)px/.exec(fontSpec)?.[1] ?? 12);
    w = text.length * px * 0.56;
  }
  widthCache.set(key, w);
  return w;
}

/** Shortens text with an ellipsis so it fits `maxWidth`. */
export function fitText(text: string, maxWidth: number, fontSpec: string): string {
  if (maxWidth <= 0) return '';
  if (measureText(text, fontSpec) <= maxWidth) return text;
  const ell = '…';
  let lo = 0;
  let hi = text.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (measureText(text.slice(0, mid).trimEnd() + ell, fontSpec) <= maxWidth) lo = mid;
    else hi = mid - 1;
  }
  return lo === 0 ? '' : text.slice(0, lo).trimEnd() + ell;
}

/* ------------------------------------------------------------- misc hooks */

/** Calls `handler` on Escape while `active`. */
export function useEscape(active: boolean, handler: () => void) {
  const ref = useRef(handler);
  useLayoutEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !e.defaultPrevented) ref.current();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [active]);
}

export const REDUCED_MOTION =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null;
