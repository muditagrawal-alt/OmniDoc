import { useEffect } from 'react';
import { useTransform, type MotionValue, type Variants } from 'motion/react';

/** The easing every entrance on the page shares: a quick start and a long, soft landing. */
export const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];

/** Children of a `group` rise into place one after another. */
export const rise: Variants = {
  hidden: { opacity: 0, y: 28 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.8, ease: EASE } },
};

/** A word that slides up out of its mask (see `.mask`). */
export const wordRise: Variants = {
  hidden: { y: '115%' },
  shown: { y: '0%', transition: { duration: 0.9, ease: EASE } },
};

export function group(stagger = 0.08, delay = 0): Variants {
  return { hidden: {}, shown: { transition: { staggerChildren: stagger, delayChildren: delay } } };
}

/**
 * The app scrolls inside its own panels, so the body never scrolls. The landing page is one long
 * document: let the window scroll while it is shown, and leave it back at the top afterwards.
 */
export function usePageScroll() {
  useEffect(() => {
    const { body, documentElement: html } = document;
    const before = { overflow: body.style.overflow, behavior: html.style.scrollBehavior };
    body.style.overflow = 'auto';
    html.style.scrollBehavior = 'smooth';
    return () => {
      html.style.scrollBehavior = before.behavior;
      window.scrollTo({ top: 0, behavior: 'instant' });
      body.style.overflow = before.overflow;
    };
  }, []);
}

/**
 * `useTransform` over a 0–1 scroll progress that holds its first and last values outside the given
 * range. Motion runs these on the browser's scroll timeline, and the browser eases back to the
 * element's base value beyond the last keyframe unless the keyframes reach both 0 and 1.
 */
export function useRamp<T>(progress: MotionValue<number>, input: number[], output: T[]): MotionValue<T> {
  const from = [...input];
  const to = [...output];
  if (from[0] > 0) {
    from.unshift(0);
    to.unshift(to[0]);
  }
  if (from[from.length - 1] < 1) {
    from.push(1);
    to.push(to[to.length - 1]);
  }
  return useTransform(progress, from, to);
}
