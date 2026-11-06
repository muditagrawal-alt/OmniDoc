import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { ArrowLeft, ArrowRight, X } from 'lucide-react';
import { TOUR_STEPS, endTour, startTour, tourSeen, tourTarget, useTourOpen } from '../lib/tour';
import type { TourStep } from '../lib/tour';
import styles from './Tour.module.css';

const PAD = 6;
const CARD_W = 340;
const GAP = 14;
const EDGE = 12;

type Box = { top: number; left: number; width: number; height: number };

/** Where the card goes: beside the spotlight when there is room, else above or below it, kept on screen. */
function place(box: Box | null, cardH: number) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(CARD_W, vw - EDGE * 2);
  if (!box) return { top: Math.max(EDGE, (vh - cardH) / 2), left: (vw - width) / 2, width };
  const clampLeft = (x: number) => Math.min(Math.max(EDGE, x), vw - width - EDGE);
  const clampTop = (y: number) => Math.min(Math.max(EDGE, y), vh - cardH - EDGE);
  if (box.left + box.width + GAP + width + EDGE <= vw && box.width < vw / 2) {
    return { top: clampTop(box.top), left: box.left + box.width + GAP, width };
  }
  if (box.top - GAP - cardH >= EDGE) {
    return { top: box.top - GAP - cardH, left: clampLeft(box.left + box.width - width), width };
  }
  return { top: clampTop(box.top + box.height + GAP), left: clampLeft(box.left + box.width - width), width };
}

/**
 * A guided tour of the workspace: a spotlight on one part of the screen at a time, with a card that
 * says what it does. Arrow keys or the buttons move through it, Esc leaves. It opens once on its own
 * for each account (userKey) in a browser; startTour() opens it again.
 */
export function Tour({ userKey }: { userKey: string }) {
  const open = useTourOpen();
  const reduce = useReducedMotion();
  const [steps, setSteps] = useState<TourStep[]>([]);
  const [index, setIndex] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [cardH, setCardH] = useState(200);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);

  // The first visit to the workspace on this browser opens the tour, once the screen has settled.
  useEffect(() => {
    if (tourSeen(userKey)) return;
    const t = window.setTimeout(startTour, 1200);
    return () => window.clearTimeout(t);
  }, [userKey]);

  // On opening: only the steps whose element is on screen now.
  useEffect(() => {
    if (!open) return;
    setSteps(TOUR_STEPS.filter((s) => !s.target || tourTarget(s.target)));
    setIndex(0);
  }, [open]);

  const step = steps[index];
  const close = useCallback(() => endTour(userKey), [userKey]);
  const next = useCallback(() => (index >= steps.length - 1 ? close() : setIndex((i) => i + 1)), [index, steps.length, close]);
  const back = useCallback(() => setIndex((i) => Math.max(0, i - 1)), []);

  const measure = useCallback(() => {
    const el = step?.target ? tourTarget(step.target) : null;
    if (!el) {
      setBox(null);
      return;
    }
    const r = el.getBoundingClientRect();
    setBox({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 });
  }, [step]);

  useLayoutEffect(() => {
    if (!open || !step) return;
    measure();
    const onChange = () => measure();
    window.addEventListener('resize', onChange);
    window.addEventListener('scroll', onChange, true);
    return () => {
      window.removeEventListener('resize', onChange);
      window.removeEventListener('scroll', onChange, true);
    };
  }, [open, step, measure]);

  useLayoutEffect(() => {
    if (cardRef.current) setCardH(cardRef.current.offsetHeight);
  }, [step, box]);

  useEffect(() => {
    if (!open || !step) return;
    nextRef.current?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        next();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        back();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, step, next, back, close]);

  if (!open || !step) return null;
  const at = place(box, cardH);
  const spring = reduce ? { duration: 0 } : { type: 'spring' as const, stiffness: 380, damping: 36 };
  const last = index === steps.length - 1;

  return createPortal(
    <div className={styles.layer}>
      {/* The dim with a hole: one box whose huge shadow darkens everything else. Clicks on the dim do nothing. */}
      {box ? (
        <motion.div className={styles.spotlight} initial={false}
          animate={{ top: box.top, left: box.left, width: box.width, height: box.height }} transition={spring} />
      ) : (
        <div className={styles.dim} />
      )}
      <AnimatePresence mode="wait" initial={false}>
        <motion.div key={step.id} ref={cardRef} className={styles.card} role="dialog" aria-modal="true"
          aria-labelledby="tour-title" aria-describedby="tour-body"
          style={{ top: at.top, left: at.left, width: at.width }}
          initial={reduce ? false : { opacity: 0, y: 6, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={reduce ? undefined : { opacity: 0, y: -4 }} transition={{ duration: 0.2 }}>
          <div className={styles.head}>
            <span className={styles.count}>{index + 1} of {steps.length}</span>
            <button type="button" className={styles.skip} onClick={close} aria-label="Leave the tour">
              <X size={15} strokeWidth={1.75} />
            </button>
          </div>
          <h2 id="tour-title" className={styles.title}>{step.title}</h2>
          <p id="tour-body" className={styles.body}>{step.body}</p>
          <div className={styles.foot}>
            <div className={styles.dots} aria-hidden="true">
              {steps.map((s, i) => <span key={s.id} data-on={i === index || undefined} data-done={i < index || undefined} />)}
            </div>
            <div className={styles.buttons}>
              {index > 0 && (
                <button type="button" className="btn btn-ghost btn-sm" onClick={back}>
                  <ArrowLeft size={14} strokeWidth={1.75} /> Back
                </button>
              )}
              <button ref={nextRef} type="button" className="btn btn-primary btn-sm" onClick={next}>
                {index === 0 ? 'Show me around' : last ? 'Done' : 'Next'} {!last && <ArrowRight size={14} strokeWidth={1.75} />}
              </button>
            </div>
          </div>
          {index === 0 && (
            <button type="button" className={styles.later} onClick={close}>Not now</button>
          )}
        </motion.div>
      </AnimatePresence>
    </div>,
    document.body,
  );
}
