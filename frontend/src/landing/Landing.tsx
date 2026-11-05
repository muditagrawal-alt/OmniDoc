import { useEffect, useState } from 'react';
import {
  ArrowRight, BookOpenCheck, FileSearch, Fingerprint, GitCompareArrows, Code2, Globe2, KeyRound,
  Languages, Lock, ScanText, ShieldCheck, Sparkles, Table2,
} from 'lucide-react';
import type { AuthMethods } from '../api';
import { useTheme } from '../lib/theme';
import { BrandMark } from '../components/BrandMark';
import Threads from '../components/reactbits/Threads';
import RotatingText from '../components/reactbits/RotatingText';
import CardSwap from '../components/reactbits/CardSwap';
import SpotlightCard from '../components/reactbits/SpotlightCard';
import CountUp from '../components/reactbits/CountUp';
import LogoLoop from '../components/reactbits/LogoLoop';
import ShinyText from '../components/reactbits/ShinyText';
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

const FEATURES = [
  {
    icon: BookOpenCheck, size: 'wide', title: 'Every claim has a source',
    text: 'Answers cite the page they came from. Click a citation and the document opens with the sentence highlighted. Each sentence is checked against its evidence before you see it.',
    proof: '[3] Annual report 2023, page 42',
  },
  {
    icon: ScanText, title: 'Reads what others skip',
    text: 'Scanned pages, photos of receipts, tables, charts and recordings. OCR covers English and nine Indian languages; figures are read by a vision model.',
    proof: 'OCR in 10 languages',
  },
  { icon: Table2, title: 'Fields into a table', text: 'Pull invoice numbers, totals, dates or any field you name from a hundred documents at once, each value with its citation. Download as CSV.', proof: 'CSV with citations' },
  { icon: GitCompareArrows, title: 'Compare two versions', text: 'Changed clauses, added sections and moved figures between two drafts, sentence by sentence.', proof: '+ added  − removed  ~ changed' },
  { icon: Globe2, title: 'A map of your library', text: 'People, companies, places and amounts linked across every document, on a 3D globe you can search.', proof: 'Knowledge graph' },
  { icon: Languages, title: 'Ask in your language', text: 'Ask in Hindi, Marathi, Tamil or seven other languages about documents written in English, and read the answer in yours.', proof: 'हिन्दी · தமிழ் · বাংলা' },
  { icon: ShieldCheck, size: 'wide', title: 'Redact before you share', text: 'Finds Aadhaar (checksum-verified), PAN, GSTIN, IFSC, card, passport and phone numbers, and downloads a truly redacted copy: the text is removed, not covered.', proof: 'Aadhaar · PAN · GSTIN · IFSC' },
] as const;

const STEPS = [
  { n: '01', title: 'Add your documents', text: 'Drop in PDFs, scans, slides, spreadsheets, e-mails or recordings. They are indexed in seconds, privately to your account.' },
  { n: '02', title: 'Ask in your own words', text: 'In English or an Indian language. OmniDoc plans the question, finds the evidence, computes figures exactly and writes the answer.' },
  { n: '03', title: 'Check the source', text: 'Every claim links to its page. One click shows the sentence in the original document, so you never have to take an answer on trust.' },
];

const PRIVACY = [
  { icon: Fingerprint, text: 'Passkeys and authenticator apps. No passwords, and no e-mail needed to sign up.' },
  { icon: KeyRound, text: 'Your own API key stays in your browser, unless you choose to keep it on the server, encrypted.' },
  { icon: Lock, text: 'No IP addresses, no trackers, no ads. A session keeps only a device label like "Chrome on macOS".' },
  { icon: FileSearch, text: 'Download everything as a zip, or delete your account and every document with it, at any time.' },
  { icon: Code2, text: 'Open source under the MIT licence: read every line, or run it yourself, fully offline with Ollama.' },
];

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  return reduced;
}

/** The product page signed-out visitors see first: what OmniDoc does, then sign-in or the demo. */
export default function Landing({ methods, onSignIn, onTryDemo, demoBusy, demoError }: LandingProps) {
  const { resolved } = useTheme();
  const reduced = usePrefersReducedMotion();
  const dark = resolved === 'dark';
  const accent = dark ? '#4589ff' : '#0f62fe';
  const canSignUp = !!methods.passkey;

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
    <div className={styles.page}>
      <a className={styles.skip} href="#main">Skip to content</a>
      <header className={styles.nav}>
        <a className={styles.brand} href="#top" aria-label="OmniDoc home">
          <BrandMark size={24} /> OmniDoc
        </a>
        <nav className={styles.links} aria-label="Sections">
          <a href="#features">Features</a>
          <a href="#how">How it works</a>
          <a href="#benchmarks">Benchmarks</a>
          <a href="#privacy">Privacy</a>
          <a href={REPO} target="_blank" rel="noreferrer">GitHub</a>
        </nav>
        <div className={styles.navActions}>
          <button type="button" className="btn btn-ghost" onClick={() => onSignIn('start')}>Sign in</button>
          {methods.demo && (
            <button type="button" className="btn btn-primary" onClick={onTryDemo} disabled={demoBusy}>Try the demo</button>
          )}
        </div>
      </header>

      <main id="main">
        <section className={styles.hero} id="top">
          <div className={styles.threads} aria-hidden="true">
            <Threads color={accent} amplitude={1} distance={0.1} enableMouseInteraction={!reduced} paused={reduced} opacity={dark ? 0.55 : 0.4} />
          </div>
          <div className={styles.heroText}>
            <span className={styles.badge}>
              <Sparkles size={14} strokeWidth={1.75} />
              <ShinyText text="Free and open source · no card · no e-mail" color={dark ? '#9aa3b2' : '#4a5263'} shineColor={accent} speed={3} disabled={reduced} />
            </span>
            <h1 className={styles.title}>
              Ask your{' '}
              <RotatingText
                texts={DOCUMENT_KINDS}
                mainClassName={styles.rotating}
                staggerDuration={0.02}
                rotationInterval={2600}
                auto={!reduced}
                splitBy="characters"
              />
              <br />
              and check every answer.
            </h1>
            <p className={styles.lede}>
              OmniDoc reads PDFs, scans, slides, spreadsheets and recordings, answers in plain language, and links
              every claim to the page and sentence it came from.
            </p>
            <div className={styles.ctas}>
              {primary}
              {secondary}
            </div>
            {demoError && <p role="alert" className={styles.error}>{demoError}</p>}
            <p className={styles.fine}>
              {canSignUp ? 'Sign up with a passkey in ten seconds. ' : ''}Three answers on us, then your own free model key.
            </p>
          </div>
          <div className={styles.heroVisual}>
            <CardSwap items={SCREENS} width={560} height={350} cardDistance={46} verticalDistance={52} delay={4200}
              autoplay={!reduced} pauseOnHover theme={dark ? 'dark' : 'light'} cardRadius={14} skewAmount={2} />
          </div>
        </section>

        <section className={styles.loops} aria-label="What OmniDoc reads">
          <LogoLoop logos={FORMAT_LOGOS}
            speed={36} gap={14} logoHeight={30} fadeOut fadeOutColor={dark ? '#0f1115' : '#f4f5f8'} pauseOnHover ariaLabel="Formats" />
          <LogoLoop logos={LANGUAGE_LOGOS}
            speed={28} direction="right" gap={30} logoHeight={30} fadeOut fadeOutColor={dark ? '#0f1115' : '#f4f5f8'} pauseOnHover ariaLabel="Languages" />
        </section>

        <section className={styles.section} id="features" aria-labelledby="features-title">
          <p className={styles.eyebrow}>What it does</p>
          <h2 id="features-title" className={styles.h2}>Answers you can verify, from documents you already have.</h2>
          <div className={styles.bento}>
            {FEATURES.map((f) => (
              <SpotlightCard key={f.title} className={styles.card} data-size={'size' in f ? f.size : undefined}
                spotlightColor={dark ? 'rgba(69, 137, 255, 0.22)' : 'rgba(15, 98, 254, 0.12)'} theme={dark ? 'dark' : 'light'}>
                <f.icon size={22} strokeWidth={1.6} className={styles.cardIcon} />
                <h3>{f.title}</h3>
                <p>{f.text}</p>
                <span className={styles.proof}>{f.proof}</span>
              </SpotlightCard>
            ))}
          </div>
        </section>

        <section className={styles.section} id="how" aria-labelledby="how-title">
          <p className={styles.eyebrow}>How it works</p>
          <h2 id="how-title" className={styles.h2}>Three steps, and the last one is yours.</h2>
          <ol className={styles.steps}>
            {STEPS.map((s) => (
              <li key={s.n}>
                <span className={styles.stepNo}>{s.n}</span>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className={styles.section} id="benchmarks" aria-labelledby="bench-title">
          <p className={styles.eyebrow}>Measured, not claimed</p>
          <h2 id="bench-title" className={styles.h2}>Public benchmarks, run on free models.</h2>
          <div className={styles.stats}>
            <div className={styles.stat}>
              <span className={styles.statValue}><CountUp to={70.7} decimals={1} duration={1.6} suffix="%" /></span>
              <span className={styles.statName}>FinanceBench</span>
              <span className={styles.statNote}>All 150 questions on SEC filings. Standard retrieval pipelines score near 50%.</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statValue}><CountUp to={57.3} decimals={1} duration={1.6} suffix="%" /></span>
              <span className={styles.statName}>MMLongBench-Doc</span>
              <span className={styles.statNote}>255 questions on long PDFs with tables, charts and images. Published document systems: 50 to 65%.</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statValue}><CountUp to={0.732} decimals={3} duration={1.6} /></span>
              <span className={styles.statName}>BEIR SciFact, nDCG@10</span>
              <span className={styles.statNote}>Retrieval alone on 300 scientific claims, scored exactly with no judge model.</span>
            </div>
          </div>
          <p className={styles.method}>
            Answers are graded by a judge model from another family than the one that wrote them. Every run, its settings
            and every graded answer are in the repository. <a href={`${REPO}/tree/main/benchmarks`} target="_blank" rel="noreferrer">Read the method</a>
          </p>
        </section>

        <section className={`${styles.section} ${styles.split}`} id="privacy" aria-labelledby="privacy-title">
          <div>
            <p className={styles.eyebrow}>Privacy and security</p>
            <h2 id="privacy-title" className={styles.h2}>It keeps as little about you as it can.</h2>
            <p className={styles.sectionLede}>
              Your documents and conversations are private to your account. Everything else is designed so there is
              nothing to leak: no passwords, no e-mail, no addresses.
            </p>
          </div>
          <ul className={styles.privacy}>
            {PRIVACY.map((p) => (
              <li key={p.text}>
                <p.icon size={18} strokeWidth={1.75} />
                <span>{p.text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className={styles.section} aria-labelledby="free-title">
          <p className={styles.eyebrow}>How it stays free</p>
          <h2 id="free-title" className={styles.h2}>Good document AI should not depend on a credit card.</h2>
          <div className={styles.tiers}>
            <div>
              <span className={styles.tierStep}>First</span>
              <h3>Three answers on us</h3>
              <p>Every new account, and every visit to the demo, starts with three answers on OmniDoc's own free model keys.</p>
            </div>
            <div>
              <span className={styles.tierStep}>Then</span>
              <h3>Your own free key</h3>
              <p>Gemini, Groq, NVIDIA, OpenRouter, Mistral and others all have free tiers. Paste a key and keep going; it stays in your browser.</p>
            </div>
            <div>
              <span className={styles.tierStep}>Or</span>
              <h3>Run it yourself</h3>
              <p>One Docker command on your own machine, with local models through Ollama: nothing leaves your computer.</p>
            </div>
          </div>
        </section>

        <section className={styles.final} aria-labelledby="final-title">
          <h2 id="final-title" className={styles.h2}>See it on a real library.</h2>
          <p className={styles.sectionLede}>
            {methods.demo
              ? 'The demo opens a sample library: two annual reports, a contract, a scanned invoice and a summary in Hindi, from a fictional company. No account needed.'
              : 'Create an account and add your first document.'}
          </p>
          <div className={styles.ctas}>
            {primary}
            {secondary}
          </div>
        </section>
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
  );
}
