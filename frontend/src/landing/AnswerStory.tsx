import { useRef, useState, type ReactNode } from 'react';
import {
  AnimatePresence, motion, useMotionValueEvent, useReducedMotion, useScroll, useTransform, type MotionValue,
} from 'motion/react';
import { Check, FileText, ShieldCheck } from 'lucide-react';
import { RiseHeading } from './scroll';
import { useRamp } from './motion';
import page from './Landing.module.css';
import styles from './AnswerStory.module.css';

/*
 * A question from the demo library, followed through the pipeline as the visitor scrolls. Every
 * figure comes from the sample annual reports (deploy/demo/make_samples.py), so the demo gives the
 * same answer.
 */
const QUESTION = 'How much did Kestrel’s revenue grow in FY2025, and what drove it?';

const STAGES = [
  {
    title: 'You ask', status: 'Reading the question',
    text: 'In plain words, in English or one of nine Indian languages, about one document or the whole library.',
  },
  {
    title: 'It plans', status: 'Planning 3 steps',
    text: 'The question is split into the steps that answer it: which figures, which years, which documents.',
  },
  {
    title: 'It finds the evidence', status: 'Searching 5 documents',
    text: 'It searches every page by meaning and by exact words, tables included, and a reranker keeps the passages that answer.',
  },
  {
    title: 'It does the maths', status: 'Calculating',
    text: 'Growth rates and shares are calculated with SymPy, from numbers that have to appear in the evidence.',
  },
  {
    title: 'It checks every sentence', status: '3 of 3 sentences supported',
    text: 'Each sentence is checked against the passage it cites before you see it. A citation opens that sentence on its page.',
  },
];

const PLAN = ['Revenue in FY2025 and FY2024', 'Growth of each revenue segment', 'What the chief executive says drove it'];

const SLICE = 1 / STAGES.length;

/** Visible from `a`–`b` (fading in) until `c`–`d` (fading out); without `c` and `d` it stays. */
function useLayer(p: MotionValue<number>, a: number, b: number, c?: number, d?: number) {
  const still = useReducedMotion();
  // Offsets stay inside 0–1: Motion hands these to the browser's own animation engine, which rejects others.
  const input = c === undefined || d === undefined ? [a, b] : [a, b, c, d];
  const opacity = useRamp(p, input, input.length === 2 ? [0, 1] : [0, 1, 1, 0]);
  const lift = input.length === 2 ? [28, 0] : [28, 0, 0, -28];
  const y = useRamp(p, input, still ? lift.map(() => 0) : lift);
  return { opacity, y };
}

function Layer({ p, at, children, className }: {
  p: MotionValue<number>; at: [number, number, number?, number?]; children: ReactNode; className?: string;
}) {
  const style = useLayer(p, at[0], at[1], at[2], at[3]);
  return <motion.div className={`${styles.layer} ${className ?? ''}`} style={style}>{children}</motion.div>;
}

/** One element arriving at progress `at`. */
function Bit({ p, at, children, className, x = 0, y = 14 }: {
  p: MotionValue<number>; at: number; children: ReactNode; className?: string; x?: number; y?: number;
}) {
  const still = useReducedMotion();
  const opacity = useRamp(p, [at, at + 0.025], [0, 1]);
  const tx = useRamp(p, [at, at + 0.025], still ? [0, 0] : [x, 0]);
  const ty = useRamp(p, [at, at + 0.025], still ? [0, 0] : [y, 0]);
  return <motion.div className={className} style={{ opacity, x: tx, y: ty }}>{children}</motion.div>;
}

/** A highlighter stroke drawn left to right between `from` and `to`. */
function Mark({ p, from, to }: { p: MotionValue<number>; from: number; to: number }) {
  const scaleX = useRamp(p, [from, to], [0, 1]);
  return <motion.i className={styles.mark} style={{ scaleX }} aria-hidden="true" />;
}

/** Running text highlighted as if by a marker, line after line. */
function MarkText({ p, from, to, children }: { p: MotionValue<number>; from: number; to: number; children: ReactNode }) {
  const backgroundSize = useRamp(p, [from, to], ['0% 100%', '100% 100%']);
  return <motion.span className={styles.marked} style={{ backgroundSize }}>{children}</motion.span>;
}

/** A check that pops in, overshooting a little. */
function Tick({ p, at }: { p: MotionValue<number>; at: number }) {
  const scale = useRamp(p, [at, at + 0.012, at + 0.024], [0, 1.3, 1]);
  return (
    <motion.span className={styles.tick} style={{ scale }}>
      <Check size={12} strokeWidth={3} />
    </motion.span>
  );
}

function StageFill({ p, index }: { p: MotionValue<number>; index: number }) {
  const scaleX = useRamp(p, [index * SLICE, (index + 1) * SLICE], [0, 1]);
  return <motion.span className={styles.fill} style={{ scaleX }} />;
}

function Cite({ n }: { n: number }) {
  return <span className={styles.cite}>{n}</span>;
}

export default function AnswerStory() {
  const track = useRef<HTMLDivElement>(null);
  const still = useReducedMotion();
  const { scrollYProgress: p } = useScroll({ target: track, offset: ['start start', 'end end'] });
  const [active, setActive] = useState(0);
  useMotionValueEvent(p, 'change', (v) => setActive(Math.min(STAGES.length - 1, Math.max(0, Math.floor(v / SLICE)))));

  const typedCount = useRamp(p, [0.02, 0.15], [0, QUESTION.length]);
  const typed = useTransform(typedCount, (c) => (still ? QUESTION : QUESTION.slice(0, Math.round(c))));
  const caret = useRamp(p, [0.15, 0.16], [1, 0]);
  const unused = useRamp(p, [0.55, 0.57], [1, 0.38]);
  const unusedTag = useRamp(p, [0.555, 0.575], [0, 1]);

  return (
    <section id="how" className={styles.story} aria-labelledby="how-title">
      <div className={styles.head}>
        <RiseHeading id="how-title" className={page.h2} text="What happens after you ask" />
      </div>

      <div ref={track} className={styles.track}>
        <div className={styles.sticky}>
          <div className={styles.segments} aria-hidden="true">
            {STAGES.map((s, i) => <span key={s.title}><StageFill p={p} index={i} /></span>)}
          </div>

          <ol className={styles.stages}>
            {STAGES.map((s, i) => (
              <motion.li key={s.title} data-active={i === active || undefined}
                animate={{ opacity: i === active ? 1 : i < active ? 0.5 : 0.3 }} transition={{ duration: 0.4 }}>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
                <span className={styles.fillTrack} aria-hidden="true"><StageFill p={p} index={i} /></span>
              </motion.li>
            ))}
          </ol>

          <p className={styles.srOnly}>
            For example, asked how much Kestrel’s revenue grew in FY2025 and what drove it, OmniDoc answers that revenue
            grew 16.5%, from INR 1,102 crore to INR 1,284 crore, mostly from subscriptions, citing page 1 of the 2025
            annual report.
          </p>

          <div className={styles.panel} aria-hidden="true">
            <div className={styles.panelBar}>
              <span className={styles.panelTitle}>Kestrel demo library · 5 documents</span>
              <span className={styles.status} data-done={active === STAGES.length - 1 || undefined}>
                <AnimatePresence mode="wait" initial={false}>
                  <motion.span key={active} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
                    {STAGES[active].status}
                  </motion.span>
                </AnimatePresence>
              </span>
            </div>

            <div className={styles.thread}>
              <div className={styles.question}>
                <motion.span>{typed}</motion.span>
                <motion.span className={styles.caretWrap} style={{ opacity: caret }}><span className={styles.caret} /></motion.span>
              </div>

              <div className={styles.work}>
                <Layer p={p} at={[0.19, 0.23, 0.37, 0.41]} className={styles.plan}>
                  <span className={styles.label}>Plan</span>
                  {PLAN.map((step, i) => (
                    <Bit key={step} p={p} at={0.23 + i * 0.04} x={-18} y={0} className={styles.planStep}>
                      <span className={styles.planNo}>{i + 1}</span> {step}
                    </Bit>
                  ))}
                </Layer>

                <Layer p={p} at={[0.4, 0.44, 0.57, 0.61]} className={styles.evidence}>
                  <span className={styles.label}>Evidence the reranker kept</span>
                  <Bit p={p} at={0.42} x={30} y={0} className={styles.source}>
                    <span className={styles.sourceHead}><FileText size={13} /> Annual Report 2025 · page 1 <em>Table 1</em></span>
                    <div className={styles.rows}>
                      <div className={`${styles.row} ${styles.rowHead}`}><span>INR crore</span><span>FY2025</span><span>FY2024</span><span>Change</span></div>
                      <div className={styles.row}><Mark p={p} from={0.49} to={0.52} /><span>Revenue</span><span>1,284</span><span>1,102</span><span>16.5%</span></div>
                      <div className={styles.row}><Mark p={p} from={0.51} to={0.54} /><span>Subscription revenue</span><span>962</span><span>801</span><span>20.1%</span></div>
                      <div className={styles.row}><span>Services revenue</span><span>322</span><span>301</span><span>7.0%</span></div>
                    </div>
                  </Bit>
                  <Bit p={p} at={0.45} x={30} y={0} className={styles.source}>
                    <span className={styles.sourceHead}><FileText size={13} /> Annual Report 2025 · page 1 <em>Letter from the CEO</em></span>
                    <p className={styles.quote}>
                      <MarkText p={p} from={0.52} to={0.56}>Subscription revenue grew 20.1% as
                      1,840 customers renewed or expanded</MarkText>, and our largest new contract, with Northwind Logistics, began
                      in the fourth quarter.
                    </p>
                  </Bit>
                  <Bit p={p} at={0.48} x={30} y={0} className={styles.sourceWrap}>
                    <motion.div className={styles.source} style={{ opacity: unused }}>
                      <span className={styles.sourceHead}><FileText size={13} /> Annual Report 2024 · page 1</span>
                      <p className={styles.quote}>In financial year 2024 revenue was INR 1,102 crore, 14.3% more than the year before.</p>
                    </motion.div>
                    <motion.span className={styles.unused} style={{ opacity: unusedTag }}>Not needed: Table 1 has both years</motion.span>
                  </Bit>
                </Layer>

                <Layer p={p} at={[0.6, 0.64, 0.77, 0.81]} className={styles.compute}>
                  <span className={styles.label}>Calculated with SymPy</span>
                  <div className={styles.code}>
                    <Bit p={p} at={0.63} className={styles.codeLine}>
                      <span>revenue_fy2025</span><span>= 1,284</span><em>Table 1</em>
                    </Bit>
                    <Bit p={p} at={0.65} className={styles.codeLine}>
                      <span>revenue_fy2024</span><span>= 1,102</span><em>Table 1</em>
                    </Bit>
                    <Bit p={p} at={0.67} className={styles.codeLine}>
                      <span>growth</span><span>= (1,284 − 1,102) ÷ 1,102 = <b>16.5%</b></span>
                    </Bit>
                    <Bit p={p} at={0.69} className={styles.codeLine}>
                      <span>from_subscriptions</span><span>= (962 − 801) ÷ 182 = <b>88.5%</b></span>
                    </Bit>
                  </div>
                  <Bit p={p} at={0.72} className={styles.verified}>
                    <ShieldCheck size={15} /> 16.5% matches Table 1 · every input was found in the evidence
                  </Bit>
                </Layer>

                <Layer p={p} at={[0.8, 0.84]} className={styles.answer}>
                  <span className={styles.label}>Answer</span>
                  <Bit p={p} at={0.83} className={styles.sentence}>
                    <Tick p={p} at={0.855} />
                    <span>Revenue grew <b>16.5%</b>, from INR 1,102 crore to INR 1,284 crore <Cite n={1} />.</span>
                  </Bit>
                  <Bit p={p} at={0.87} className={styles.sentence}>
                    <Tick p={p} at={0.895} />
                    <span>Subscriptions drove most of it: up <b>20.1%</b> to INR 962 crore, 88.5% of the increase <Cite n={1} />.</span>
                  </Bit>
                  <Bit p={p} at={0.91} className={styles.sentence}>
                    <Tick p={p} at={0.935} />
                    <span>The chief executive credits 1,840 customers renewing or expanding, and the new Northwind Logistics
                      contract from the fourth quarter <Cite n={2} />.</span>
                  </Bit>
                  <Bit p={p} at={0.95} className={styles.sources}>
                    <span><Cite n={1} /> Annual Report 2025, p. 1, Table 1</span>
                    <span><Cite n={2} /> Annual Report 2025, p. 1</span>
                    <span className={styles.supported}><ShieldCheck size={13} /> Supported by sources</span>
                  </Bit>
                </Layer>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
