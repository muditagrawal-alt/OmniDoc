import { useSyncExternalStore, type CSSProperties } from 'react';

/** Inline style that exposes a family colour token as --swatch for .swatch elements. */
export function swatchStyle(cssVarName: string): CSSProperties {
  return { '--swatch': `var(${cssVarName})` } as CSSProperties;
}

const REDUCED_MOTION = '(prefers-reduced-motion: reduce)';

function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia(REDUCED_MOTION);
  mq.addEventListener('change', cb);
  return () => mq.removeEventListener('change', cb);
}

/** Live prefers-reduced-motion. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}

/** True when the keyboard event comes from a text field (so global shortcuts stay out of the way). */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}
