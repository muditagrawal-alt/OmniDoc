import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  MotionConfig, motion, useInView, useMotionValueEvent, useReducedMotion, useScroll, useTransform, type Variants,
} from 'motion/react';
import {
  ArrowRight, Check, Code2, FileSearch, Fingerprint, KeyRound, Languages, Lock, Mic, ScanText, ShieldCheck,
  Sparkles, Zap,
} from 'lucide-react';
import type { AuthMethods } from '../api';
import { useTheme } from '../lib/theme';
import { BrandMark } from '../components/BrandMark';
import LiquidChrome from '../components/reactbits/LiquidChrome';
import Threads from '../components/reactbits/Threads';
import RotatingText from '../components/reactbits/RotatingText';
import CardSwap from '../components/reactbits/CardSwap';
import SpotlightCard from '../components/reactbits/SpotlightCard';
import CountUp from '../components/reactbits/CountUp';
import LogoLoop from '../components/reactbits/LogoLoop';
import ShinyText from '../components/reactbits/ShinyText';
import AnswerStory from './AnswerStory';
import FeatureTour from './FeatureTour';
import { Eyebrow, MaskedWords, Reveal, RiseHeading, ScrollProgress, ScrollWords, StackCards } from './scroll';
import { EASE, group, rise, usePageScroll, useRamp, wordRise } from './motion';
import styles from './Landing.module.css';

interface LandingProps {
  methods: AuthMethods;
  onSignIn: (step: 'start' | 'signup') => void;
  onTryDemo: () => void;
  demoBusy?: boolean;
  demoError?: string | null;
}

const REPO = 'https://github.com/muditagrawal-alt/OmniDoc';

const SCREENS = [
  { image: '/landing/answer.webp', title: 'Cited answers', alt: 'An answer with numbered citations to the pages it came from' },
  { image: '/landing/viewer.webp', title: 'The sentence, highlighted', alt: 'A cited passage highlighted on the original page' },
  { image: '/landing/extract.webp', title: 'Fields into a table', alt: 'Values extracted from several documents into a table' },
  { image: '/landing/compare.webp', title: 'Two versions compared', alt: 'Changed figures and clauses between two documents' },
  { image: '/landing/globe.webp', title: 'Knowledge globe', alt: 'People, companies and figures from the library on a 3D globe' },
  { image: '/landing/hindi.webp', title: 'Ask in Hindi', alt: 'A question and answer in Hindi about an English document' },
];

const FORMATS = ['PDF', 'Scanned pages', 'Word', 'Excel', 'PowerPoint', 'E-mail', 'EPUB', 'Web pages', 'Audio', 'Video', 'Photos'];
const LANGUAGES = ['English', 'हिन्दी', 'मराठी', 'বাংলা', 'தமிழ்', 'తెలుగు', 'ಕನ್ನಡ', 'ગુજરાતી', 'ਪੰਜਾਬੀ', 'മലയാളം'];
// Built once: the animated components restart (and re-render) whenever these props change identity.
const DOCUMENT_KINDS = ['annual reports', 'contracts', 'research papers', 'scanned forms', 'invoices', 'board decks'];
const FORMAT_LOGOS = FORMATS.map((f) => ({ node: <span className={styles.chip}>{f}</span>, title: f }));
const LANGUAGE_LOGOS = LANGUAGES.map((l) => ({ node: <span className={styles.lang}>{l}</span>, title: l }));

const NAV = [
  { id: 'how', label: 'How it works' },
  { id: 'features', label: 'Features' },
  { id: 'benchmarks', label: 'Benchmarks' },
  { id: 'privacy', label: 'Privacy' },
];
const WATCHED = ['top', 'how', 'features', 'more', 'benchmarks', 'privacy', 'free'];

const STATEMENT =
  'Most document AI gives you an answer and asks you to trust it. OmniDoc shows you the *page,* the *sentence* and the *check* behind every claim.';

const MORE = [
  {
    icon: ScanText, size: 'wide', title: 'Reads scans and photos',
    text: 'Scanned pages, photos of receipts, tables and charts. OCR covers English and nine Indian languages, and figures are read by a vision model.',
    proof: 'OCR in 10 languages',
  },
  {
    icon: Mic, title: 'Recordings too',
    text: 'Audio and video are transcribed when you add them, so a meeting can be searched and asked about like any document.',
    proof: 'Audio · Video',
  },
  {
    icon: ShieldCheck, title: 'Redact before you share',
    text: 'Finds Aadhaar (checksum-verified), PAN, GSTIN, IFSC, card and phone numbers, and downloads a copy with the text removed, not covered.',
    proof: 'Aadhaar · PAN · GSTIN · IFSC',
  },
  {
    icon: Zap, size: 'wide', title: 'Runs on free models',
    text: 'Answers come from free hosted models, or from models on your own computer through Ollama. No paid API anywhere in the pipeline.',
    proof: 'Free tiers or fully offline',
  },
] as const;

const BENCH = [
  {
    to: 70.7, decimals: 1, suffix: '%', share: 0.707, name: 'FinanceBench', mark: 50,
    legend: 'Marker: standard retrieval pipelines, near 50%',
    note: 'All 150 questions on SEC filings, answered by free models.',
  },
  {
    to: 57.3, decimals: 1, suffix: '%', share: 0.573, name: 'MMLongBench-Doc', band: [50, 65],
    legend: 'Band: published document systems, 50 to 65%',
    note: '255 questions on long PDFs with tables, charts and images.',
  },
  {
    to: 0.732, decimals: 3, suffix: '', share: 0.732, name: 'BEIR SciFact, nDCG@10',
    legend: 'Scored exactly, with no judge model',
    note: 'Retrieval alone, on 300 scientific claims.',
  },
];

const PRIVACY = [
  { icon: Fingerprint, text: 'Passkeys and authenticator apps. No passwords, and no e-mail needed to sign up.' },
  { icon: KeyRound, text: 'Your own API key stays in your browser, unless you choose to keep it on the server, encrypted.' },
  { icon: Lock, text: 'No IP addresses, no trackers, no ads. A session keeps only a device label like "Chrome on macOS".' },
  { icon: FileSearch, text: 'Download everything as a zip, or delete your account and every document with it, at any time.' },
  { icon: Code2, text: 'Open source under the MIT licence: read every line, or run it yourself, fully offline with Ollama.' },
];

const PROVIDERS = ['Gemini', 'Groq', 'NVIDIA', 'OpenRouter', 'Mistral', 'Cerebras', 'GitHub Models'];

const tiltIn: Variants = {
  hidden: { opacity: 0, y: 56, rotateX: 16 },
  shown: { opacity: 1, y: 0, rotateX: 0, transition: { duration: 1, ease: EASE } },
};

const pop: Variants = {
  hidden: { opacity: 0, scale: 0.6 },
  shown: { opacity: 1, scale: 1, transition: { type: 'spring', stiffness: 420, damping: 22 } },
};

/** Which watched section is under the middle of the screen. */
function useActiveSection(ids: string[]) {
  const [active, setActive] = useState<string | null>(null);
  useEffect(() => {
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) setActive(entry.target.id);
    }, { rootMargin: '-45% 0px -50% 0px' });
    for (const id of ids) {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, [ids]);
  return active;
}

function Nav({ methods, onSignIn, onTryDemo, demoBusy }: Omit<LandingProps, 'demoError'>) {
  const { scrollY } = useScroll();
  const [hidden, setHidden] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const active = useActiveSection(WATCHED);
  useMotionValueEvent(scrollY, 'change', (y) => {
    const previous = scrollY.getPrevious() ?? 0;
    if (y > previous && y > 360) setHidden(true);
    else if (y < previous - 4) setHidden(false);
    setScrolled(y > 12);
  });

  return (
    <motion.header className={styles.nav} data-scrolled={scrolled || undefined}
      initial={{ y: -80, opacity: 0 }} animate={{ y: hidden ? -96 : 0, opacity: 1 }}
      transition={{ duration: 0.45, ease: EASE }} onFocusCapture={() => setHidden(false)}>
      <div className={styles.navInner}>
        <a className={styles.brand} href="#top" aria-label="OmniDoc home">
          <BrandMark size={24} /> OmniDoc
        </a>
        <nav className={styles.links} aria-label="Sections">
          {NAV.map((link) => (
            <a key={link.id} href={`#${link.id}`} aria-current={active === link.id ? 'true' : undefined}>
              {active === link.id && (
                <motion.span layoutId="nav-pill" className={styles.linkPill}
                  transition={{ type: 'spring', stiffness: 480, damping: 38 }} />
              )}
              <span>{link.label}</span>
            </a>
          ))}
          <a href={REPO} target="_blank" rel="noreferrer"><span>GitHub</span></a>
        </nav>
        <div className={styles.navActions}>
          <button type="button" className="btn btn-ghost" onClick={() => onSignIn('start')}>Sign in</button>
          {methods.demo && (
            <button type="button" className="btn btn-primary" onClick={onTryDemo} disabled={demoBusy}>Try the demo</button>
          )}
        </div>
      </div>
    </motion.header>
  );
}

function Hero({ primary, secondary, canSignUp, demoError, dark }: {
  primary: ReactNode; secondary: ReactNode; canSignUp: boolean; demoError?: string | null; dark: boolean;
}) {
  const still = useReducedMotion();
  const { scrollY } = useScroll();
  const textY = useTransform(scrollY, [0, 520], [0, -110]);
  const textOpacity = useTransform(scrollY, [0, 440], [1, 0]);
  const textBlur = useTransform(scrollY, [0, 440], ['blur(0px)', 'blur(6px)']);

  const stage = useRef<HTMLDivElement>(null);
  const { scrollYProgress: rising } = useScroll({ target: stage, offset: ['start end', 'center center'] });
  const rotateX = useTransform(rising, [0, 1], [30, 0]);
  const scale = useTransform(rising, [0, 1], [0.84, 1]);
  const chromeY = useTransform(rising, [0, 1], [120, -40]);
  const chipLeft = useTransform(rising, [0, 1], [140, 0]);
  const chipRight = useTransform(rising, [0, 1], [220, 0]);
  const chipOpacity = useRamp(rising, [0.4, 0.85], [0, 1]);

  return (
    <section className={styles.hero} id="top" aria-labelledby="hero-title">
      <motion.div className={styles.heroText} style={still ? undefined : { y: textY, opacity: textOpacity, filter: textBlur }}>
        <motion.div className={styles.heroInner} variants={group(0.06, 0.15)} initial="hidden" animate="shown">
          <motion.span variants={rise} className={styles.badge}>
            <Sparkles size={14} strokeWidth={1.75} />
            <ShinyText text="Free and open source · no card · no e-mail" color={dark ? '#a3aab7' : '#4a5263'}
              shineColor={dark ? '#4589ff' : '#0f62fe'} speed={3} disabled={!!still} />
          </motion.span>
          <h1 id="hero-title" className={styles.title}>
            <MaskedWords text="Ask your" />{' '}
            <span className={styles.mask}>
              <motion.span className={styles.word} variants={wordRise}>
                <RotatingText texts={DOCUMENT_KINDS} mainClassName={styles.rotating} staggerDuration={0.02}
                  rotationInterval={2600} auto={!still} splitBy="characters" />
              </motion.span>
            </span>
            <br />
            <MaskedWords text="and check every answer." />
          </h1>
          <motion.p variants={rise} className={styles.lede}>
            OmniDoc reads PDFs, scans, slides, spreadsheets and recordings, answers in plain language, and links every
            claim to the page and sentence it came from.
          </motion.p>
          <motion.div variants={rise} className={styles.ctas}>
            {primary}
            {secondary}
          </motion.div>
          {demoError && <p role="alert" className={styles.error}>{demoError}</p>}
          <motion.p variants={rise} className={styles.fine}>
            {canSignUp ? 'Sign up with a passkey in ten seconds. ' : ''}Three answers on us, then your own free model key.
          </motion.p>
        </motion.div>
      </motion.div>

      <div ref={stage} className={styles.stage}>
        <motion.div className={styles.chrome} aria-hidden="true" style={still ? undefined : { y: chromeY }}
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1.6, delay: 0.3 }}>
          <LiquidChrome color={dark ? '#dfe7ff' : '#ffffff'} lightMode={!dark} speed={0.18} amplitude={0.32}
            detail={4} thickness={1.1} roughness={0.28} interactive={!still} intro={!still} maxDevicePixelRatio={1.5} />
        </motion.div>
        <motion.div className={styles.frame} style={still ? undefined : { rotateX, scale }}>
          <div className={styles.frameBar} aria-hidden="true">
            <span className={styles.dots}><i /><i /><i /></span>
            <span className={styles.frameUrl}>omnidoc · your library</span>
          </div>
          <img src="/landing/answer.webp" width={1440} height={900} fetchPriority="high"
            alt="OmniDoc answering a question about quarterly sales, with numbered citations and a sentence check" />
        </motion.div>
        <motion.div className={styles.floatChip} data-side="left" aria-hidden="true"
          style={still ? undefined : { y: chipLeft, opacity: chipOpacity }}>
          <span className={styles.floatCite}>1</span> Every claim cited to its page
        </motion.div>
        <motion.div className={styles.floatChip} data-side="right" aria-hidden="true"
          style={still ? undefined : { y: chipRight, opacity: chipOpacity }}>
          <ShieldCheck size={15} /> 5 of 5 sentences supported
        </motion.div>
      </div>
    </section>
  );
}

function MoreCards({ dark }: { dark: boolean }) {
  return (
    <section className={styles.section} id="more" aria-labelledby="more-title">
      <Eyebrow>And the parts most tools skip</Eyebrow>
      <RiseHeading id="more-title" className={styles.h2} text="It reads what others leave out." />
      <motion.div className={styles.bento} variants={group(0.1)} initial="hidden" whileInView="shown"
        viewport={{ once: true, amount: 0.2 }}>
        {MORE.map((f) => (
          <motion.div key={f.title} variants={tiltIn} className={styles.cardSlot} data-size={'size' in f ? f.size : undefined}>
            <SpotlightCard className={styles.card}
              spotlightColor={dark ? 'rgba(69, 137, 255, 0.22)' : 'rgba(15, 98, 254, 0.12)'} theme={dark ? 'dark' : 'light'}>
              <span className={styles.cardIcon}><f.icon size={20} strokeWidth={1.6} /></span>
              <h3>{f.title}</h3>
              <p>{f.text}</p>
              <span className={styles.proof}>{f.proof}</span>
            </SpotlightCard>
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}

function Benchmarks() {
  return (
    <section className={styles.section} id="benchmarks" aria-labelledby="bench-title">
      <Eyebrow>Measured, not claimed</Eyebrow>
      <RiseHeading id="bench-title" className={styles.h2} text="Public benchmarks, run on free models." />
      <motion.div className={styles.stats} variants={group(0.14)} initial="hidden" whileInView="shown"
        viewport={{ once: true, amount: 0.3 }}>
        {BENCH.map((b) => (
          <motion.div key={b.name} className={styles.stat} variants={tiltIn}>
            <span className={styles.statValue}><CountUp to={b.to} decimals={b.decimals} duration={1.8} suffix={b.suffix} /></span>
            <span className={styles.statName}>{b.name}</span>
            <span className={styles.meter} aria-hidden="true">
              {'band' in b && b.band && (
                <span className={styles.meterBand} style={{ '--from': `${b.band[0]}%`, '--to': `${b.band[1]}%` } as CSSProperties} />
              )}
              <motion.span className={styles.meterFill} variants={{
                hidden: { scaleX: 0 }, shown: { scaleX: b.share, transition: { duration: 1.8, delay: 0.25, ease: EASE } },
              }} />
              {'mark' in b && b.mark && <span className={styles.meterMark} style={{ '--at': `${b.mark}%` } as CSSProperties} />}
            </span>
            <span className={styles.meterLegend}>{b.legend}</span>
            <span className={styles.statNote}>{b.note}</span>
          </motion.div>
        ))}
      </motion.div>
      <Reveal>
        <p className={styles.method}>
          Answers are graded by a judge model from another family than the one that wrote them. Every run, its settings
          and every graded answer are in the repository. <a href={`${REPO}/tree/main/benchmarks`} target="_blank" rel="noreferrer">Read the method</a>
        </p>
      </Reveal>
    </section>
  );
}

function Privacy() {
  return (
    <section className={`${styles.section} ${styles.split}`} id="privacy" aria-labelledby="privacy-title">
      <div className={styles.splitHead}>
        <Eyebrow>Privacy and security</Eyebrow>
        <RiseHeading id="privacy-title" className={styles.h2} text="It keeps as little about you as it can." />
        <Reveal delay={0.1}>
          <p className={styles.sectionLede}>
            Your documents and conversations are private to your account. Everything else is designed so there is
            nothing to leak: no passwords, no e-mail, no addresses.
          </p>
        </Reveal>
      </div>
      <ul className={styles.privacy}>
        {PRIVACY.map((p) => (
          <motion.li key={p.text} initial={{ opacity: 0, x: 56 }} whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, amount: 0.8 }} transition={{ duration: 0.8, ease: EASE }}>
            <motion.span className={styles.privacyIcon} initial={{ rotate: -90, scale: 0.4 }} whileInView={{ rotate: 0, scale: 1 }}
              viewport={{ once: true, amount: 0.8 }} transition={{ type: 'spring', stiffness: 260, damping: 18, delay: 0.15 }}>
              <p.icon size={18} strokeWidth={1.75} />
            </motion.span>
            <span>{p.text}</span>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}

function AnswersLeft() {
  return (
    <motion.div className={styles.answersLeft} variants={group(0.18, 0.2)} initial="hidden" whileInView="shown"
      viewport={{ once: true, amount: 0.6 }}>
      <div className={styles.answerDots}>
        {[1, 2, 3].map((n) => (
          <motion.span key={n} variants={pop}><Check size={16} strokeWidth={2.5} /></motion.span>
        ))}
      </div>
      <motion.p variants={rise} className={styles.answersNote}>
        3 of 3 free answers left · <span>Use your own free key</span>
      </motion.p>
    </motion.div>
  );
}

function ProviderChips() {
  return (
    <motion.div className={styles.providerChips} variants={group(0.07, 0.15)} initial="hidden" whileInView="shown"
      viewport={{ once: true, amount: 0.6 }}>
      {PROVIDERS.map((p) => <motion.span key={p} variants={pop}>{p}</motion.span>)}
      <motion.p variants={rise} className={styles.keyNote}><Lock size={13} /> The key stays in this browser</motion.p>
    </motion.div>
  );
}

function TerminalLines() {
  const lines = [
    { prompt: '$', text: `git clone ${REPO}` },
    { prompt: '$', text: 'cd OmniDoc && docker compose --profile local up -d' },
    { prompt: '→', text: 'OmniDoc is running on http://localhost:8000' },
  ];
  return (
    <motion.div className={styles.terminal} variants={group(0.35, 0.2)} initial="hidden" whileInView="shown"
      viewport={{ once: true, amount: 0.6 }}>
      <div className={styles.terminalBar}><i /><i /><i /></div>
      {lines.map((l) => (
        <motion.p key={l.text} variants={{ hidden: { opacity: 0, x: -12 }, shown: { opacity: 1, x: 0, transition: { duration: 0.5 } } }}>
          <span>{l.prompt}</span> {l.text}
        </motion.p>
      ))}
    </motion.div>
  );
}

function Free() {
  return (
    <section className={styles.section} id="free" aria-labelledby="free-title">
      <Eyebrow>How it stays free</Eyebrow>
      <RiseHeading id="free-title" className={styles.h2} text="Good document AI should not depend on a credit card." />
      <StackCards items={[
        {
          step: 'First', title: 'Three answers on us', visual: <AnswersLeft />,
          text: 'Every new account, and every visit to the demo, starts with three answers on OmniDoc’s own free model keys.',
        },
        {
          step: 'Then', title: 'Your own free key', visual: <ProviderChips />,
          text: 'Gemini, Groq, NVIDIA, OpenRouter, Mistral and others all have free tiers. Paste a key and keep going.',
        },
        {
          step: 'Or', title: 'Run it yourself', visual: <TerminalLines />,
          text: 'One Docker command on your own machine, with local models through Ollama: nothing leaves your computer.',
        },
      ]} />
    </section>
  );
}

function Final({ demo, primary, secondary, dark }: { demo: boolean; primary: ReactNode; secondary: ReactNode; dark: boolean }) {
  const still = useReducedMotion();
  const ref = useRef<HTMLElement>(null);
  const near = useInView(ref, { margin: '200px 0px' });
  const { scrollYProgress } = useScroll({ target: ref, offset: ['start end', 'start 0.3'] });
  const clipPath = useTransform(scrollYProgress, [0, 1], ['inset(10% 7% 10% 7% round 56px)', 'inset(0% 0% 0% 0% round 28px)']);
  return (
    <motion.section ref={ref} className={styles.final} aria-labelledby="final-title" style={still ? undefined : { clipPath }}>
      <div className={styles.finalThreads} aria-hidden="true">
        <Threads color={dark ? '#4589ff' : '#0f62fe'} amplitude={1} distance={0.1} enableMouseInteraction={!still}
          paused={!!still || !near} opacity={dark ? 0.55 : 0.4} />
      </div>
      <div className={styles.finalText}>
        <RiseHeading id="final-title" className={styles.h2} text="See it on a real library." />
        <Reveal delay={0.1}>
          <p className={styles.sectionLede}>
            {demo
              ? 'The demo opens a sample library: two annual reports, a contract, a scanned invoice and a summary in Hindi, from a fictional company. No account needed.'
              : 'Create an account and add your first document.'}
          </p>
        </Reveal>
        <Reveal delay={0.2} className={styles.ctas}>
          {primary}
          {secondary}
        </Reveal>
      </div>
      <Reveal className={styles.finalSwap} x={80} y={0} amount={0.3}>
        <CardSwap items={SCREENS} width={520} height={325} cardDistance={44} verticalDistance={50} delay={4200}
          autoplay={!still} pauseOnHover theme={dark ? 'dark' : 'light'} cardRadius={14} skewAmount={2} />
      </Reveal>
    </motion.section>
  );
}

/** The product page signed-out visitors see first, told as one scroll: what OmniDoc does, then sign-in or the demo. */
export default function Landing({ methods, onSignIn, onTryDemo, demoBusy, demoError }: LandingProps) {
  const { resolved } = useTheme();
  const dark = resolved === 'dark';
  const canSignUp = !!methods.passkey;
  usePageScroll();

  useEffect(() => {
    document.title = 'OmniDoc · Ask your documents, check every answer';
  }, []);

  const primary = methods.demo ? (
    <button type="button" className={`btn btn-primary ${styles.cta}`} onClick={onTryDemo} disabled={demoBusy}>
      {demoBusy ? <span className="spinner" /> : null} Try the demo <ArrowRight size={16} strokeWidth={1.75} />
    </button>
  ) : (
    <button type="button" className={`btn btn-primary ${styles.cta}`} onClick={() => onSignIn(canSignUp ? 'signup' : 'start')}>
      Get started <ArrowRight size={16} strokeWidth={1.75} />
    </button>
  );
  const secondary = (
    <button type="button" className={`btn btn-secondary ${styles.cta}`} onClick={() => onSignIn(canSignUp ? 'signup' : 'start')}>
      {canSignUp ? 'Create a free account' : 'Sign in'}
    </button>
  );

  return (
    <MotionConfig reducedMotion="user">
      <div className={styles.page}>
        <ScrollProgress />
        <a className={styles.skip} href="#main">Skip to content</a>
        <Nav methods={methods} onSignIn={onSignIn} onTryDemo={onTryDemo} demoBusy={demoBusy} />

        <main id="main">
          <Hero primary={primary} secondary={secondary} canSignUp={canSignUp} demoError={demoError} dark={dark} />

          <Reveal className={styles.loops} y={24}>
            <section aria-label="What OmniDoc reads" className={styles.loopsInner}>
              <LogoLoop logos={FORMAT_LOGOS} speed={36} gap={14} logoHeight={30} fadeOut
                fadeOutColor={dark ? '#0f1115' : '#f4f5f8'} pauseOnHover ariaLabel="Formats" />
              <LogoLoop logos={LANGUAGE_LOGOS} speed={28} direction="right" gap={30} logoHeight={30} fadeOut
                fadeOutColor={dark ? '#0f1115' : '#f4f5f8'} pauseOnHover ariaLabel="Languages" />
            </section>
          </Reveal>

          <ScrollWords text={STATEMENT} />
          <AnswerStory />
          <FeatureTour />
          <MoreCards dark={dark} />
          <Benchmarks />
          <Privacy />
          <Free />
          <Final demo={!!methods.demo} primary={primary} secondary={secondary} dark={dark} />
        </main>

        <footer className={styles.footer}>
          <span className={styles.brand}><BrandMark size={18} /> OmniDoc</span>
          <span>Open source under the MIT licence · Built by <a href="https://github.com/muditagrawal-alt" target="_blank" rel="noreferrer">Mudit Agrawal</a></span>
          <span className={styles.footLinks}>
            <a href={REPO} target="_blank" rel="noreferrer">GitHub</a>
            <a href={`${REPO}/blob/main/docs/PRODUCT_PLAN.md`} target="_blank" rel="noreferrer">Roadmap</a>
            <a href="https://reactbits.dev" target="_blank" rel="noreferrer">Animations: React Bits</a>
            <span className={styles.langNote}><Languages size={13} strokeWidth={1.75} /> English</span>
          </span>
        </footer>
      </div>
    </MotionConfig>
  );
}
