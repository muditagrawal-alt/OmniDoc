import { Fragment, useRef, type CSSProperties, type ReactNode } from 'react';
import { motion, useReducedMotion, useScroll, useSpring, type MotionValue } from 'motion/react';
import { EASE, group, useRamp, wordRise } from './motion';
import styles from './Landing.module.css';

/** A thin bar along the top edge that fills as the visitor reads down the page. */
export function ScrollProgress() {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, { stiffness: 180, damping: 32, restDelta: 0.001 });
  return <motion.div className={styles.progress} style={{ scaleX }} aria-hidden="true" />;
}

interface RevealProps {
  children: ReactNode;
  className?: string;
  delay?: number;
  x?: number;
  y?: number;
  scale?: number;
  rotateX?: number;
  amount?: number;
}

/** Fades its children into place the first time they scroll into view. */
export function Reveal({ children, className, delay = 0, x = 0, y = 32, scale = 1, rotateX = 0, amount = 0.25 }: RevealProps) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, x, y, scale, rotateX }}
      whileInView={{ opacity: 1, x: 0, y: 0, scale: 1, rotateX: 0 }}
      viewport={{ once: true, amount }}
      transition={{ duration: 0.9, delay, ease: EASE }}
    >
      {children}
    </motion.div>
  );
}

/** Words of `text`, each in a mask so it can rise into view (used with `wordRise`). */
export function MaskedWords({ text }: { text: string }) {
  const words = text.split(' ');
  return (
    <>
      {words.map((word, i) => (
        <Fragment key={i}>
          <span className={styles.mask}>
            <motion.span className={styles.word} variants={wordRise}>{word}</motion.span>
          </span>
          {i < words.length - 1 ? ' ' : null}
        </Fragment>
      ))}
    </>
  );
}

/** A section heading whose words rise one after another when it scrolls into view. */
export function RiseHeading({ text, id, className }: { text: string; id?: string; className?: string }) {
  return (
    <motion.h2 id={id} className={className} variants={group(0.045)} initial="hidden" whileInView="shown"
      viewport={{ once: true, amount: 0.6 }}>
      <MaskedWords text={text} />
    </motion.h2>
  );
}

/** An eyebrow label that draws its leading rule and then fades its text in. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <motion.p className={styles.eyebrow} initial="hidden" whileInView="shown" viewport={{ once: true, amount: 1 }}
      variants={group(0.15)}>
      <motion.span className={styles.eyebrowRule} variants={{
        hidden: { scaleX: 0 }, shown: { scaleX: 1, transition: { duration: 0.6, ease: EASE } },
      }} />
      <motion.span variants={{ hidden: { opacity: 0, x: -8 }, shown: { opacity: 1, x: 0, transition: { duration: 0.5 } } }}>
        {children}
      </motion.span>
    </motion.p>
  );
}

/**
 * A statement pinned to the screen while its words light up one by one as the visitor scrolls.
 * Words written as `*word*` are drawn in the accent colour.
 */
export function ScrollWords({ text }: { text: string }) {
  const ref = useRef<HTMLElement>(null);
  const still = useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] });
  const words = text.split(' ');
  return (
    <section ref={ref} className={styles.statement} aria-label="Why OmniDoc">
      <div className={styles.statementSticky}>
        <p className={styles.statementText}>
          {words.map((word, i) => (
            <Fragment key={i}>
              <LitWord progress={scrollYProgress} still={!!still}
                from={(i / words.length) * 0.8} to={((i + 1) / words.length) * 0.8 + 0.02}>
                {word}
              </LitWord>
              {i < words.length - 1 ? ' ' : null}
            </Fragment>
          ))}
        </p>
      </div>
    </section>
  );
}

function LitWord({ children, progress, from, to, still }: {
  children: string; progress: MotionValue<number>; from: number; to: number; still: boolean;
}) {
  const opacity = useRamp(progress, [from, to], [0.14, 1]);
  const y = useRamp(progress, [from, to], [10, 0]);
  const marked = /^\*(.+?)\*(\W*)$/.exec(children);
  return (
    <motion.span className={marked ? styles.lit : undefined} style={still ? undefined : { opacity, y, display: 'inline-block' }}>
      {marked ? marked[1] : children}
      {marked ? <span className={styles.litTail}>{marked[2]}</span> : null}
    </motion.span>
  );
}

export interface StackItem {
  step: string;
  title: string;
  text: string;
  visual: ReactNode;
}

/** Cards that pin one after another and pile up, each new one sliding over the last. */
export function StackCards({ items }: { items: StackItem[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start start', 'end end'] });
  return (
    <div ref={ref} className={styles.stack}>
      {items.map((item, i) => (
        <StackCard key={item.title} item={item} index={i} count={items.length} progress={scrollYProgress} />
      ))}
    </div>
  );
}

function StackCard({ item, index, count, progress }: {
  item: StackItem; index: number; count: number; progress: MotionValue<number>;
}) {
  const still = useReducedMotion();
  const scale = useRamp(progress, [index / count, 1], [1, 1 - (count - 1 - index) * 0.05]);
  const dim = useRamp(progress, [index / count, 1], [0, (count - 1 - index) * 0.18]);
  return (
    <div className={styles.stackSlot} style={{ '--i': index } as CSSProperties}>
      <motion.article className={styles.stackCard} style={still ? undefined : { scale }}>
        <div className={styles.stackText}>
          <span className={styles.stackStep}>{item.step}</span>
          <h3>{item.title}</h3>
          <p>{item.text}</p>
        </div>
        <div className={styles.stackVisual}>{item.visual}</div>
        {!still && <motion.span className={styles.stackShade} style={{ opacity: dim }} aria-hidden="true" />}
      </motion.article>
    </div>
  );
}
