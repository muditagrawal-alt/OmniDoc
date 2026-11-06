import { useRef, useState } from 'react';
import type { FormEvent, KeyboardEvent } from 'react';
import { AnimatePresence, motion, useScroll } from 'motion/react';
import { ArrowRight } from 'lucide-react';
import { api } from '../api';
import { Reveal, RiseHeading } from './scroll';
import { EASE, useRamp } from './motion';
import styles from './Feedback.module.css';

const RATINGS = [
  { value: 1, label: 'Not useful' },
  { value: 2, label: 'Rough' },
  { value: 3, label: 'Okay' },
  { value: 4, label: 'Good' },
  { value: 5, label: 'Very useful' },
];
const MAX_MESSAGE = 2000;

/** One to five, as a radio group: click, or the arrow keys once focused. */
function Rating({ value, onChange }: { value: number | null; onChange: (value: number) => void }) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault();
    const step = e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 1;
    const next = Math.min(5, Math.max(1, (value ?? 3) + step));
    onChange(next);
    const group = e.currentTarget;
    requestAnimationFrame(() => group.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };
  return (
    <div className={styles.rating} role="radiogroup" aria-labelledby="feedback-rating-label" onKeyDown={onKeyDown}>
      {RATINGS.map((r) => {
        const selected = r.value === value;
        return (
          <button key={r.value} type="button" role="radio" aria-checked={selected} aria-label={`${r.value}: ${r.label}`}
            tabIndex={selected || (value === null && r.value === 1) ? 0 : -1} className={styles.score}
            data-filled={(value !== null && r.value <= value) || undefined} onClick={() => onChange(r.value)}>
            {selected && (
              <motion.span layoutId="feedback-score" className={styles.scorePill}
                transition={{ type: 'spring', stiffness: 520, damping: 36 }} />
            )}
            <span>{r.value}</span>
          </button>
        );
      })}
    </div>
  );
}

/**
 * The last screen of the product page: a card to say what worked and what did not. It goes to the
 * server's administrator; no account, address or IP is kept with it.
 */
export default function Feedback() {
  const ref = useRef<HTMLElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'start start'] });
  const tilt = useRamp(scrollYProgress, [0.15, 0.85], [10, 0]);
  const [rating, setRating] = useState<number | null>(null);
  const [message, setMessage] = useState('');
  const [contact, setContact] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (message.trim().length < 3) {
      setError('Write a few words first.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.sendFeedback(message.trim(), rating, contact.trim() || undefined);
      setSent(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const again = () => {
    setSent(false);
    setRating(null);
    setMessage('');
    setContact('');
  };

  return (
    <section ref={ref} className={styles.page} id="feedback" aria-labelledby="feedback-title">
      <div className={styles.inner}>
        <div className={styles.text}>
          <RiseHeading id="feedback-title" className={styles.title} text="What should OmniDoc do better?" />
          <Reveal delay={0.1}>
            <p className={styles.lede}>
              A wrong answer, a citation that opened the wrong page, a document it could not read, or something you wish it
              did. One person builds OmniDoc and reads every message.
            </p>
          </Reveal>
          <Reveal delay={0.2}>
            <dl className={styles.facts}>
              <div><dt>Kept</dt><dd>Your rating, your message, and a way to reply only if you leave one.</dd></div>
              <div><dt>Not kept</dt><dd>Your account, IP address or anything else about you.</dd></div>
            </dl>
          </Reveal>
        </div>

        <motion.div className={styles.cardWrap} style={{ rotateX: tilt }}>
          <Reveal y={48} amount={0.2}>
            <div className={styles.card}>
              <AnimatePresence mode="wait" initial={false}>
                {sent ? (
                  <motion.div key="thanks" className={styles.thanks} role="status"
                    initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
                    transition={{ duration: 0.4, ease: EASE }}>
                    <svg className={styles.tick} viewBox="0 0 52 52" aria-hidden="true">
                      <motion.circle cx="26" cy="26" r="24" fill="none" strokeWidth="2"
                        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.6, ease: EASE }} />
                      <motion.path d="M15 27l7 7 15-16" fill="none" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
                        initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.4, delay: 0.45, ease: EASE }} />
                    </svg>
                    <h3>Thank you. It is on its way.</h3>
                    <p>{contact.trim() ? 'If it needs a reply, you will hear back.' : 'You left no contact, so there will be no reply, but it will be read.'}</p>
                    <button type="button" className="btn btn-secondary" onClick={again}>Send something else</button>
                  </motion.div>
                ) : (
                  <motion.form key="form" className={styles.form} onSubmit={send} noValidate
                    initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -12 }}
                    transition={{ duration: 0.4, ease: EASE }}>
                    <div>
                      <div className={styles.labelRow}>
                        <span id="feedback-rating-label" className="field-label">How useful was it?</span>
                        <span className={styles.ratingWord} aria-hidden="true">
                          {rating ? RATINGS[rating - 1].label : 'Optional'}
                        </span>
                      </div>
                      <Rating value={rating} onChange={setRating} />
                    </div>
                    <div>
                      <div className={styles.labelRow}>
                        <label className="field-label" htmlFor="feedback-message">Your feedback</label>
                        <span className={styles.count} data-near={message.length > MAX_MESSAGE - 200 || undefined}>
                          {message.length}/{MAX_MESSAGE}
                        </span>
                      </div>
                      <textarea id="feedback-message" className={`field ${styles.message}`} rows={5} maxLength={MAX_MESSAGE}
                        value={message} onChange={(e) => setMessage(e.target.value)}
                        placeholder="The answer about FY2025 revenue cited page 3, but the figure is on page 7."
                        aria-invalid={!!error} aria-describedby={error ? 'feedback-error' : undefined} />
                    </div>
                    <div>
                      <label className="field-label" htmlFor="feedback-contact">
                        How to reply <span className={styles.optional}>optional</span>
                      </label>
                      <input id="feedback-contact" className="field" maxLength={120} autoComplete="off" value={contact}
                        onChange={(e) => setContact(e.target.value)} placeholder="An e-mail address or a GitHub username" />
                    </div>
                    {error && <p id="feedback-error" role="alert" className={styles.error}>{error}</p>}
                    <button type="submit" className={`btn btn-primary ${styles.send}`} disabled={busy || message.trim().length < 3}>
                      {busy ? <span className="spinner" /> : null} Send feedback <ArrowRight size={16} strokeWidth={1.75} />
                    </button>
                  </motion.form>
                )}
              </AnimatePresence>
            </div>
          </Reveal>
        </motion.div>
      </div>
    </section>
  );
}
