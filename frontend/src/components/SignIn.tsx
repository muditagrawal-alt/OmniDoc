import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeft, Mail } from 'lucide-react';
import { api } from '../api';
import type { AuthMethods, User } from '../api';
import { BrandMark } from './BrandMark';
import styles from './SignIn.module.css';

interface SignInProps {
  methods: AuthMethods;
  initialError?: string | null;
  onSignedIn: (user: User) => void;
}

const RESEND_AFTER_S = 60;

function GoogleLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

function GitHubLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">
      <path d="M12 .5C5.7.5.5 5.7.5 12a11.5 11.5 0 0 0 7.9 10.9c.6.1.8-.3.8-.6v-2.1c-3.2.7-3.9-1.4-3.9-1.4-.5-1.3-1.3-1.7-1.3-1.7-1-.7.1-.7.1-.7 1.2.1 1.8 1.2 1.8 1.2 1 1.8 2.8 1.3 3.5 1 .1-.8.4-1.3.7-1.6-2.6-.3-5.3-1.3-5.3-5.7 0-1.3.5-2.3 1.2-3.1-.1-.3-.5-1.5.1-3.1 0 0 1-.3 3.2 1.2a11 11 0 0 1 5.8 0c2.2-1.5 3.2-1.2 3.2-1.2.6 1.6.2 2.8.1 3.1.8.8 1.2 1.9 1.2 3.1 0 4.4-2.7 5.4-5.3 5.7.4.4.8 1.1.8 2.2v3.2c0 .3.2.7.8.6A11.5 11.5 0 0 0 23.5 12C23.5 5.7 18.3.5 12 .5z" />
    </svg>
  );
}

/** The sign-in page of a hosted OmniDoc: Google, GitHub, or a six-digit code sent by e-mail. */
export function SignIn({ methods, initialError, onSignedIn }: SignInProps) {
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  useEffect(() => {
    if (step === 'code') codeRef.current?.focus();
  }, [step]);

  const sendCode = async (e?: FormEvent) => {
    e?.preventDefault();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError('Enter a valid e-mail address.');
      return;
    }
    setBusy(true);
    try {
      await api.requestCode(email.trim());
      setStep('code');
      setCode('');
      setWait(RESEND_AFTER_S);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (value: string) => {
    setError(null);
    setBusy(true);
    try {
      onSignedIn(await api.verifyCode(email.trim(), value));
    } catch (err) {
      setError((err as Error).message);
      setCode('');
      codeRef.current?.focus();
    } finally {
      setBusy(false);
    }
  };

  const onCode = (value: string) => {
    const digits = value.replace(/\D/g, '').slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && !busy) void verify(digits);
  };

  const oauth = methods.google || methods.github;

  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="signin-title">
        <div className={styles.brand}>
          <BrandMark size={28} />
          <span>OmniDoc</span>
        </div>
        {step === 'email' ? (
          <>
            <h1 id="signin-title" className={styles.title}>Sign in</h1>
            <p className={styles.sub}>Your documents and conversations are private to your account.</p>
            {oauth && (
              <div className={styles.providers}>
                {methods.google && (
                  <a className={`btn btn-secondary ${styles.provider}`} href={api.oauthUrl('google')}>
                    <GoogleLogo /> Continue with Google
                  </a>
                )}
                {methods.github && (
                  <a className={`btn btn-secondary ${styles.provider}`} href={api.oauthUrl('github')}>
                    <GitHubLogo /> Continue with GitHub
                  </a>
                )}
              </div>
            )}
            {oauth && methods.email && <div className={styles.divider}><span>or</span></div>}
            {methods.email && (
              <form onSubmit={sendCode} noValidate>
                <label className="field-label" htmlFor="signin-email">E-mail</label>
                <input
                  id="signin-email"
                  className="field"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!error}
                  aria-describedby={error ? 'signin-error' : undefined}
                />
                <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={busy}>
                  {busy ? <span className="spinner" /> : <Mail size={16} strokeWidth={1.75} />} E-mail me a sign-in code
                </button>
              </form>
            )}
            {!oauth && !methods.email && (
              <p className={styles.sub}>No sign-in method is configured on this server yet. Ask its administrator.</p>
            )}
          </>
        ) : (
          <>
            <h1 id="signin-title" className={styles.title}>Check your e-mail</h1>
            <p className={styles.sub}>
              We sent a six-digit code to <strong>{email.trim()}</strong>. It expires in 10 minutes.
            </p>
            <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void verify(code); }} noValidate>
              <label className="field-label" htmlFor="signin-code">Sign-in code</label>
              <input
                id="signin-code"
                ref={codeRef}
                className={`field ${styles.code}`}
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                maxLength={6}
                value={code}
                onChange={(e) => onCode(e.target.value)}
                aria-invalid={!!error}
                aria-describedby={error ? 'signin-error' : undefined}
              />
              <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={busy || code.length !== 6}>
                {busy && <span className="spinner" />} Sign in
              </button>
            </form>
            <div className={styles.row}>
              <button type="button" className={styles.link} onClick={() => { setStep('email'); setError(null); }}>
                <ArrowLeft size={14} strokeWidth={1.75} /> Use another address
              </button>
              <button type="button" className={styles.link} disabled={wait > 0 || busy} onClick={() => void sendCode()}>
                {wait > 0 ? `Send a new code in ${wait}s` : 'Send a new code'}
              </button>
            </div>
          </>
        )}
        {error && (
          <p id="signin-error" role="alert" className={styles.error}>
            {error}
          </p>
        )}
      </section>
      <p className={styles.footnote}>OmniDoc keeps your e-mail address to identify you. Nothing else about you is collected.</p>
    </main>
  );
}
