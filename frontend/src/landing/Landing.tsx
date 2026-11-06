import { useEffect, useRef, useState, type ReactNode } from 'react';
import { MotionConfig, motion, useInView, useMotionValueEvent, useReducedMotion, useScroll, useTransform } from 'motion/react';
import { ArrowRight, Languages } from 'lucide-react';
import type { AuthMethods } from '../api';
import { useTheme } from '../lib/theme';
import { useSettings } from '../lib/settings';
import { ChromaWaves } from '../components/backgrounds/ChromaWaves';
import { BrandMark } from '../components/BrandMark';
import { ThemeSwitch } from '../components/ThemeSwitch';
import LiquidChrome from '../components/reactbits/LiquidChrome';
import Threads from '../components/reactbits/Threads';
import RotatingText from '../components/reactbits/RotatingText';
import CardSwap from '../components/reactbits/CardSwap';
import CountUp from '../components/reactbits/CountUp';
import LogoLoop from '../components/reactbits/LogoLoop';
import AnswerStory from './AnswerStory';
import FeatureTour from './FeatureTour';
import Feedback from './Feedback';
import { MaskedWords, Reveal, RiseHeading, ScrollProgress, ScrollWords, StackCards } from './scroll';
import { EASE, group, rise, usePageScroll, wordRise } from './motion';
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

const LANGUAGES = ['English', 'हिन्दी', 'मराठी', 'বাংলা', 'தமிழ்', 'తెలుగు', 'ಕನ್ನಡ', 'ગુજરાતી', 'ਪੰਜਾਬੀ', 'മലയാളം'];
// Built once: the animated components restart (and re-render) whenever these props change identity.
const DOCUMENT_KINDS = ['annual reports', 'contracts', 'research papers', 'scanned forms', 'invoices', 'board decks'];
const LANGUAGE_LOGOS = LANGUAGES.map((l) => ({ node: <span className={styles.lang}>{l}</span>, title: l }));

const NAV = [
  { id: 'how', label: 'How it works' },
  { id: 'features', label: 'Features' },
  { id: 'benchmarks', label: 'Benchmarks' },
  { id: 'privacy', label: 'Privacy' },
  { id: 'feedback', label: 'Feedback' },
];
const WATCHED = ['top', 'how', 'features', 'more', 'benchmarks', 'privacy', 'free', 'feedback'];

const STATEMENT =
  'Every answer cites its sources. Click a citation and the document opens at that *page,* with the *sentence* highlighted.';

const MORE = [
  {
    title: 'Scans and photos',
    text: 'OCR in English and nine Indian languages for scanned pages and photographed receipts. Charts and figures are read by a vision model.',
  },
  {
    title: 'Recordings',
    text: 'Audio and video are transcribed when you add them, so a meeting can be searched and asked about like any document.',
  },
  {
    title: 'Redaction',
    text: 'Finds Aadhaar, PAN, GSTIN, IFSC, card and phone numbers, and downloads a copy with the text removed rather than covered.',
  },
  {
    title: 'Free models',
    text: 'Answers come from the free tiers of hosted models, or from models on your own computer through Ollama.',
  },
];

const BENCH = [
  {
    to: 70.7, decimals: 1, suffix: '%', name: 'FinanceBench',
    note: '150 questions on SEC filings. Standard retrieval pipelines score near 50%.',
  },
  {
    to: 57.3, decimals: 1, suffix: '%', name: 'MMLongBench-Doc',
    note: '255 questions on long PDFs with tables, charts and images. Published document systems score 50 to 65%.',
  },
  {
    to: 0.732, decimals: 3, suffix: '', name: 'BEIR SciFact, nDCG@10',
    note: 'Retrieval alone, on 300 scientific claims, scored without a judge model.',
  },
];

const PRIVACY = [
  'Sign in with a passkey or an authenticator app. There is no password, and no e-mail address is needed.',
  'Your own API key stays in your browser, unless you choose to keep it on the server, encrypted.',
  'No IP addresses, trackers or ads. A session keeps only a device label such as "Chrome on macOS".',
  'Download everything as a zip, or delete your account and every document with it, at any time.',
  'The code is open source under the MIT licence, and you can run all of it on your own machine.',
];

/**
 * Waves of light behind everything after the hero (which has its own chrome background): faded in
 * as the hero scrolls away, and not drawn at all while faded out.
 */
function Waves({ dark }: { dark: boolean }) {
  const settings = useSettings();
  const still = useReducedMotion();
  const { scrollY } = useScroll();
  const opacity = useTransform(scrollY, (y) => {
    const vh = window.innerHeight || 800;
    return Math.min(1, Math.max(0, (y - vh * 0.55) / (vh * 0.45)));
  });
  const [on, setOn] = useState(false);
  useMotionValueEvent(opacity, 'change', (v) => setOn(v > 0.01));
  return (
    <motion.div className={styles.waves} style={{ opacity }} aria-hidden="true">
      <ChromaWaves dark={dark} accent={settings.accent} still={!!still} active={on} />
    </motion.div>
  );
}

/** The logo's action on the product page: back to the top (smoothly, unless motion is reduced). */
function toTop() {
  window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
}

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
        <button type="button" className={styles.brand} onClick={toTop} aria-label="OmniDoc, back to the top">
          <BrandMark size={24} /> OmniDoc
        </button>
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
          <ThemeSwitch />
          <button type="button" className="btn btn-ghost" onClick={() => onSignIn('start')}>Sign in</button>
          {methods.demo && (
            <button type="button" className="btn btn-primary" onClick={onTryDemo} disabled={demoBusy}>Try the demo</button>
          )}
        </div>
      </div>
    </motion.header>
  );
}

function Hero({ primary, secondary, demoError, dark }: {
  primary: ReactNode; secondary: ReactNode; demoError?: string | null; dark: boolean;
}) {
  const still = useReducedMotion();
  const { scrollY } = useScroll();
  const textY = useTransform(scrollY, [0, 520], [0, -110]);
  const textOpacity = useTransform(scrollY, [0, 440], [1, 0]);
  const textBlur = useTransform(scrollY, [0, 440], ['blur(0px)', 'blur(6px)']);
  // The metal sits deeper than the page: it drifts down at a third of the scrolling speed.
  const chromeY = useTransform(scrollY, [0, 1200], [0, 400]);

  const stage = useRef<HTMLDivElement>(null);
  const { scrollYProgress: rising } = useScroll({ target: stage, offset: ['start end', 'center center'] });
  const rotateX = useTransform(rising, [0, 1], [30, 0]);
  const scale = useTransform(rising, [0, 1], [0.86, 1]);

  return (
    <section className={styles.hero} id="top" aria-labelledby="hero-title">
      <motion.div className={styles.chrome} aria-hidden="true" style={still ? undefined : { y: chromeY }}
        initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 1.4, delay: 0.2 }}>
        <LiquidChrome color={dark ? '#dfe7ff' : '#ffffff'} lightMode={!dark} speed={0.16} amplitude={0.38}
          detail={4} thickness={1.6} depth={1.1} roughness={0.25} exposure={dark ? 1.15 : 1}
          interactive={!still} intro={!still} maxDevicePixelRatio={1.5} />
      </motion.div>
      <div className={styles.scrim} aria-hidden="true" />

      <div className={styles.heroInner}>
        <motion.div className={styles.heroText} style={still ? undefined : { y: textY, opacity: textOpacity, filter: textBlur }}>
          <motion.div variants={group(0.06, 0.15)} initial="hidden" animate="shown">
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
              OmniDoc reads PDFs, scans, slides, spreadsheets and recordings, and cites the page and sentence behind
              every answer.
            </motion.p>
            <motion.div variants={rise} className={styles.ctas}>
              {primary}
              {secondary}
            </motion.div>
            {demoError && <p role="alert" className={styles.error}>{demoError}</p>}
          </motion.div>
        </motion.div>

        <div ref={stage} className={styles.stage}>
          <motion.div className={styles.frame} style={still ? undefined : { rotateX, scale }}>
            <img src="/landing/answer.webp" width={1440} height={900} fetchPriority="high"
              alt="OmniDoc answering a question about quarterly sales, with numbered citations and a sentence check" />
          </motion.div>
        </div>
      </div>
    </section>
  );
}

function More() {
  return (
    <section className={styles.section} id="more" aria-labelledby="more-title">
      <RiseHeading id="more-title" className={styles.h2} text="Also included" />
      <motion.div className={styles.columns} variants={group(0.1)} initial="hidden" whileInView="shown"
        viewport={{ once: true, amount: 0.3 }}>
        {MORE.map((item) => (
          <motion.div key={item.title} variants={rise} className={styles.column}>
            <motion.span className={styles.columnRule} variants={{
              hidden: { scaleX: 0 }, shown: { scaleX: 1, transition: { duration: 0.9, ease: EASE } },
            }} />
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </motion.div>
        ))}
      </motion.div>
    </section>
  );
}

function Benchmarks() {
  return (
    <section className={styles.section} id="benchmarks" aria-labelledby="bench-title">
      <RiseHeading id="bench-title" className={styles.h2} text="Benchmark results" />
      <Reveal delay={0.1}>
        <p className={styles.sectionLede}>
          Public benchmarks, answered by free models and graded by a judge model from a different family.
        </p>
      </Reveal>
      <ol className={styles.benchRows}>
        {BENCH.map((b) => (
          <motion.li key={b.name} initial={{ opacity: 0, x: -48 }} whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, amount: 0.6 }} transition={{ duration: 0.9, ease: EASE }}>
            <span className={styles.benchValue}><CountUp to={b.to} decimals={b.decimals} duration={1.8} suffix={b.suffix} /></span>
            <span className={styles.benchText}>
              <strong>{b.name}</strong>
              <span>{b.note}</span>
            </span>
          </motion.li>
        ))}
      </ol>
      <Reveal>
        <p className={styles.method}>
          Every run, its settings and every graded answer are in the repository.{' '}
          <a href={`${REPO}/tree/main/benchmarks`} target="_blank" rel="noreferrer">Read the method</a>
        </p>
      </Reveal>
    </section>
  );
}

function Privacy() {
  return (
    <section className={`${styles.section} ${styles.split}`} id="privacy" aria-labelledby="privacy-title">
      <div className={styles.splitHead}>
        <RiseHeading id="privacy-title" className={styles.h2} text="What it keeps about you" />
        <Reveal delay={0.1}>
          <p className={styles.sectionLede}>
            Your documents and conversations are private to your account, and the rest is kept to a minimum.
          </p>
        </Reveal>
      </div>
      <ul className={styles.privacy}>
        {PRIVACY.map((text) => (
          <motion.li key={text} initial={{ opacity: 0, y: 40 }} whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.8 }} transition={{ duration: 0.8, ease: EASE }}>
            {text}
          </motion.li>
        ))}
      </ul>
    </section>
  );
}

function Free({ dark }: { dark: boolean }) {
  return (
    <section className={styles.section} id="free" aria-labelledby="free-title">
      <RiseHeading id="free-title" className={styles.h2} text="How it stays free" />
      <StackCards dark={dark} items={[
        {
          title: 'Three answers on us',
          text: 'Every new account and every visit to the demo starts with three answers on OmniDoc’s own free model keys.',
          visual: <img src="/landing/free-answers.webp" width={1520} height={374} loading="lazy"
            alt="The question box, showing 3 of 3 free answers left and a link to use your own free key" />,
        },
        {
          title: 'Then your own free key',
          text: 'Gemini, Groq, NVIDIA, OpenRouter, Mistral, Cerebras and GitHub Models all have free tiers. Paste a key and keep going.',
          visual: <img src="/landing/own-key.webp" width={1114} height={742} loading="lazy"
            alt="The list of providers with a free tier, each with a note on its limits" />,
        },
        {
          title: 'Or run it yourself',
          text: 'One Docker command on your own machine, with local models through Ollama.',
          visual: (
            <pre className={styles.code}><code>
              <span>git clone {REPO}</span>
              <span>cd OmniDoc</span>
              <span>docker compose --profile local up -d</span>
            </code></pre>
          ),
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
  const clipPath = useTransform(scrollYProgress, [0, 1], ['inset(10% 7% 10% 7% round 40px)', 'inset(0% 0% 0% 0% round 18px)']);
  return (
    <motion.section ref={ref} className={styles.final} aria-labelledby="final-title" style={still ? undefined : { clipPath }}>
      <div className={styles.finalThreads} aria-hidden="true">
        <Threads color={dark ? '#4589ff' : '#0f62fe'} amplitude={1} distance={0.1} enableMouseInteraction={!still}
          paused={!!still || !near} opacity={dark ? 0.55 : 0.4} />
      </div>
      <div className={styles.finalText}>
        <RiseHeading id="final-title" className={styles.h2} text="Try it on the sample library" />
        <Reveal delay={0.1}>
          <p className={styles.sectionLede}>
            {demo
              ? 'Two annual reports, a contract, a scanned invoice and a summary in Hindi, from a fictional company. No account needed.'
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
  const canSignUp = !!methods.passkey || !!methods.password;
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
        <Waves dark={dark} />
        <a className={styles.skip} href="#main">Skip to content</a>
        <Nav methods={methods} onSignIn={onSignIn} onTryDemo={onTryDemo} demoBusy={demoBusy} />

        <main id="main">
          <Hero primary={primary} secondary={secondary} demoError={demoError} dark={dark} />

          <Reveal className={styles.loops} y={24}>
            <section aria-labelledby="languages-title" className={styles.loopsInner}>
              <p id="languages-title" className={styles.loopsLabel}>Ask and get answers in ten languages</p>
              <LogoLoop logos={LANGUAGE_LOGOS} speed={28} gap={36} logoHeight={34} fadeOut
                fadeOutColor={dark ? '#0f1115' : '#f4f5f8'} pauseOnHover ariaLabel="Languages" />
            </section>
          </Reveal>

          <ScrollWords text={STATEMENT} />
          <AnswerStory />
          <FeatureTour />
          <More />
          <Benchmarks />
          <Privacy />
          <Free dark={dark} />
          <Final demo={!!methods.demo} primary={primary} secondary={secondary} dark={dark} />
          <Feedback />
        </main>

        <footer className={styles.footer}>
          <button type="button" className={styles.brand} onClick={toTop} aria-label="OmniDoc, back to the top">
            <BrandMark size={18} /> OmniDoc
          </button>
          <span>Open source under the MIT licence. Built by <a href="https://github.com/muditagrawal-alt" target="_blank" rel="noreferrer">Mudit Agrawal</a></span>
          <span className={styles.footLinks}>
            <a href={REPO} target="_blank" rel="noreferrer">GitHub</a>
            <span className={styles.langNote}><Languages size={13} strokeWidth={1.75} /> English</span>
          </span>
        </footer>
      </div>
    </MotionConfig>
  );
}
