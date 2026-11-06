import { useRef, useState } from 'react';
import { motion, useMotionValueEvent, useScroll, type Variants } from 'motion/react';
import { Reveal, RiseHeading } from './scroll';
import { EASE } from './motion';
import page from './Landing.module.css';
import styles from './FeatureTour.module.css';

const TOUR = [
  {
    image: '/landing/answer.webp', title: 'Every claim has a source',
    text: 'Answers cite the pages they came from, numbered like a paper. Each sentence is checked against its evidence before you see it.',
    alt: 'An answer about quarterly sales with numbered citations and a sentence check',
  },
  {
    image: '/landing/viewer.webp', title: 'The sentence, highlighted',
    text: 'A citation opens the original document at that page with the sentence highlighted, so checking an answer takes one click.',
    alt: 'A cited passage highlighted on the original page',
  },
  {
    image: '/landing/extract.webp', title: 'Fields into a table',
    text: 'Pull invoice numbers, totals, dates or any field you name from a hundred documents at once, each value with its citation, and download a CSV.',
    alt: 'Values extracted from several documents into a table',
  },
  {
    image: '/landing/compare.webp', title: 'Two versions compared',
    text: 'Changed clauses, added sections and moved figures between two drafts of a contract or two years of a report.',
    alt: 'Changed figures and clauses between two documents',
  },
  {
    image: '/landing/globe.webp', title: 'A map of your library',
    text: 'People, companies, places and amounts linked across every document, on a 3D globe you can search and turn.',
    alt: 'People, companies and figures from the library on a 3D globe',
  },
  {
    image: '/landing/hindi.webp', title: 'Ask in your language',
    text: 'Ask in Hindi, Marathi, Tamil or seven other languages about documents written in English, and read the answer in yours.',
    alt: 'A question and answer in Hindi about an English document',
  },
];

/* The new screenshot wipes up over the last one, which sinks back a little. */
const SHOT: Variants = {
  on: { clipPath: 'inset(0% 0% 0% 0% round 0px)', scale: 1, opacity: 1 },
  past: { clipPath: 'inset(0% 0% 0% 0% round 0px)', scale: 0.94, opacity: 0.6 },
  next: { clipPath: 'inset(100% 0% 0% 0% round 0px)', scale: 1.08, opacity: 1 },
};

/** Features told one at a time: the text scrolls by while the screenshot beside it stays and changes. */
export default function FeatureTour() {
  const list = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: list, offset: ['start center', 'end center'] });
  const [active, setActive] = useState(0);
  useMotionValueEvent(scrollYProgress, 'change', (v) => {
    setActive(Math.min(TOUR.length - 1, Math.max(0, Math.floor(v * TOUR.length))));
  });

  return (
    <section id="features" className={styles.tour} aria-labelledby="features-title">
      <RiseHeading id="features-title" className={page.h2} text="What you can do with it" />

      <div className={styles.body}>
        <div ref={list} className={styles.list}>
          {TOUR.map((f, i) => (
            <motion.article key={f.title} className={styles.item} data-active={i === active || undefined}
              animate={{ opacity: i === active ? 1 : 0.28 }} transition={{ duration: 0.5, ease: EASE }}>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
              <Reveal className={styles.inlineShot} y={40} scale={0.96}>
                <img src={f.image} alt={f.alt} width={1440} height={900} loading="lazy" decoding="async" />
              </Reveal>
            </motion.article>
          ))}
        </div>

        <div className={styles.stage} aria-hidden="true">
          <div className={styles.shots}>
            {TOUR.map((f, i) => (
              <motion.img key={f.image} src={f.image} alt="" width={1440} height={900} className={styles.shot}
                style={{ zIndex: i }} variants={SHOT} initial={false}
                animate={i === active ? 'on' : i < active ? 'past' : 'next'}
                transition={{ duration: 0.9, ease: EASE }} />
            ))}
          </div>
          <div className={styles.rail}>
            {TOUR.map((f, i) => (
              <span key={f.title} data-on={i <= active || undefined}>
                {i === active && <motion.i layoutId="tour-rail" className={styles.railNow} transition={{ type: 'spring', stiffness: 400, damping: 36 }} />}
              </span>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
