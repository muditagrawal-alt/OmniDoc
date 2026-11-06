import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { ArrowLeft, ArrowRight, Check, Copy, Download, KeyRound, LifeBuoy, LockKeyhole, Mail } from 'lucide-react';
import { api } from '../api';
import type { AuthMethods, SignInResult, User } from '../api';
import { passkeysSupported } from '../lib/webauthn';
import { MIN_PASSWORD, USERNAME, passwordHint } from '../lib/passwords';
import { prefersStill, useSettings } from '../lib/settings';
import { useTheme } from '../lib/theme';
import { BrandMark } from './BrandMark';
import { PasswordInput } from './PasswordInput';
import { ThemeSwitch } from './ThemeSwitch';
import { Segmented } from './ui/Controls';
import { RingField } from './backgrounds/RingField';
import styles from './SignIn.module.css';

interface SignInProps {
  methods: AuthMethods;
  initialError?: string | null;
  /** A two-step ticket handed back by GitHub or Google sign-in */
  initialTicket?: string | null;
  /** Open on account creation instead of sign-in (the landing page's "Create a free account"). */
  initialStep?: 'start' | 'signup';
  /** Back to the product page. */
  onBack?: () => void;
  onSignedIn: (user: User) => void;
}

type Step = 'start' | 'code' | 'mfa' | 'signup' | 'recovery' | 'codes' | 'reset';

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

/** Ten one-time recovery codes, shown once, with copy and download. */
export function RecoveryCodes({ codes }: { codes: string[] }) {
  const [copied, setCopied] = useState(false);
  const asText = () => `OmniDoc recovery codes (${new Date().toISOString().slice(0, 10)})\nEach code signs in once.\n\n${codes.join('\n')}\n`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(asText());
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      /* clipboard refused: the codes stay selectable */
    }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([asText()], { type: 'text/plain' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'omnidoc-recovery-codes.txt';
    a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 5000);
  };
  return (
    <div>
      <ol className={styles.codes} aria-label="Recovery codes">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ol>
      <div className={styles.codeActions}>
        <button type="button" className="btn btn-secondary btn-sm" onClick={copy}>
          {copied ? <Check size={14} strokeWidth={1.75} /> : <Copy size={14} strokeWidth={1.75} />} {copied ? 'Copied' : 'Copy'}
        </button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={download}>
          <Download size={14} strokeWidth={1.75} /> Download .txt
        </button>
      </div>
    </div>
  );
}

/**
 * The sign-in page of a hosted OmniDoc: a username and password, a passkey, GitHub, Google or an
 * e-mailed code; creating an account with a password or a passkey (no e-mail); "forgot password"
 * with a recovery code; the authenticator-app step; and the demo.
 */
export function SignIn({ methods, initialError, initialTicket, initialStep, onBack, onSignedIn }: SignInProps) {
  const passkeys = !!methods.passkey && passkeysSupported();
  const canSignUp = passkeys || !!methods.password;
  const [step, setStep] = useState<Step>(initialTicket ? 'mfa' : initialStep === 'signup' && canSignUp ? 'signup' : 'start');
  const [signupWith, setSignupWith] = useState<'password' | 'passkey'>(methods.password ? 'password' : 'passkey');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [ticket, setTicket] = useState<string | null>(initialTicket ?? null);
  const [useRecovery, setUseRecovery] = useState(false);
  const [codes, setCodes] = useState<string[]>([]);
  const [pendingUser, setPendingUser] = useState<User | null>(null);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(initialError ?? null);
  const [busy, setBusy] = useState<string | null>(null);
  const [wait, setWait] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const settings = useSettings();
  const { resolved } = useTheme();

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  useEffect(() => {
    if (step !== 'start' && step !== 'codes') inputRef.current?.focus();
  }, [step, useRecovery]);

  const go = (next: Step) => {
    setError(null);
    setCode('');
    setPassword('');
    setUseRecovery(false);
    setStep(next);
  };

  /** Runs a sign-in action and moves on: signed in, a two-step ticket, or new recovery codes to save first. */
  const run = async (label: string, action: () => Promise<SignInResult>) => {
    setError(null);
    setBusy(label);
    try {
      const result = await action();
      if ('mfa' in result) {
        setTicket(result.mfa);
        go('mfa');
      } else if (result.recoveryCodes?.length) {
        setCodes(result.recoveryCodes);
        setPendingUser(result.user);
        go('codes');
      } else {
        onSignedIn(result.user);
      }
    } catch (err) {
      setError((err as Error).message);
      if (step === 'code' || step === 'mfa') setCode('');
    } finally {
      setBusy(null);
    }
  };

  const sendCode = async (e?: FormEvent) => {
    e?.preventDefault();
    setError(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError('Enter a valid e-mail address.');
      return;
    }
    setBusy('email');
    try {
      await api.requestCode(email.trim());
      go('code');
      setWait(RESEND_AFTER_S);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  const onDigits = (value: string, submit: (digits: string) => void) => {
    const digits = value.replace(/\D/g, '').slice(0, 6);
    setCode(digits);
    if (digits.length === 6 && !busy) submit(digits);
  };

  const cleanName = username.trim().toLowerCase();
  /** An onChange that also clears an error about the previous value. */
  const edit = (set: (value: string) => void) => (value: string) => {
    set(value);
    setError(null);
  };

  const signInPassword = (e: FormEvent) => {
    e.preventDefault();
    if (!cleanName || !password) return;
    void run('password', () => api.signInWithPassword(cleanName, password));
  };

  /** Checks what can be checked here, so a typo does not cost a round trip (and a proof of work). */
  const newPasswordProblem = () => {
    if (!USERNAME.test(cleanName)) return 'Usernames are 3 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.';
    if (password.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters for the password.`;
    return null;
  };

  const signUpPassword = (e: FormEvent) => {
    e.preventDefault();
    const problem = newPasswordProblem();
    if (problem) {
      setError(problem);
      return;
    }
    void run('signup', () => api.signUpWithPassword(cleanName, password, name.trim() || undefined));
  };

  const resetWithCode = (e: FormEvent) => {
    e.preventDefault();
    const problem = !code.trim() ? 'Enter one of your recovery codes.' : newPasswordProblem();
    if (problem) {
      setError(problem);
      return;
    }
    void run('reset', () => api.resetPassword(cleanName, code.trim(), password));
  };

  const verifyEmail = (value: string) => run('verify', () => api.verifyCode(email.trim(), value));
  const verifyTwoStep = (value: string) => run('verify', () => api.finishTwoStep(ticket || '', value));
  const oauth = methods.google || methods.github;
  const spinner = (label: string) => (busy === label ? <span className="spinner" /> : null);

  const back = (to: Step = 'start', label = 'Back') => (
    <button type="button" className={styles.link} onClick={() => go(to)}>
      <ArrowLeft size={14} strokeWidth={1.75} /> {label}
    </button>
  );

  return (
    <main className={styles.page}>
      {settings.backdrop !== 'off' && (
        <RingField className={styles.backdrop} dark={resolved === 'dark'} accent={settings.accent}
          still={settings.backdrop === 'still' || prefersStill(settings)} />
      )}
      <header className={styles.topbar}>
        {onBack ? (
          <button type="button" className={`${styles.brand} ${styles.brandLink}`} onClick={onBack} aria-label="Back to the OmniDoc home page">
            <ArrowLeft size={16} strokeWidth={1.75} className={styles.backArrow} />
            <BrandMark size={24} />
            <span>OmniDoc</span>
          </button>
        ) : (
          <div className={styles.brand}>
            <BrandMark size={24} />
            <span>OmniDoc</span>
          </div>
        )}
        <ThemeSwitch />
      </header>
      <section className={styles.card} aria-labelledby="signin-title">

        {step === 'start' && (
          <>
            <h1 id="signin-title" className={styles.title}>Sign in</h1>
            <p className={styles.sub}>Your documents and conversations are private to your account.</p>
            {methods.password && (
              <form className={styles.fields} onSubmit={signInPassword} noValidate>
                <div>
                  <label className="field-label" htmlFor="signin-username">Username</label>
                  <input id="signin-username" className="field" autoComplete="username" autoCapitalize="none" spellCheck={false}
                    maxLength={64} value={username} onChange={(e) => edit(setUsername)(e.target.value)} />
                </div>
                <div>
                  <div className={styles.labelRow}>
                    <label className="field-label" htmlFor="signin-password">Password</label>
                    <button type="button" className={styles.link} onClick={() => go('reset')}>Forgot password?</button>
                  </div>
                  <PasswordInput id="signin-password" autoComplete="current-password" value={password} onChange={edit(setPassword)} />
                </div>
                <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || !cleanName || !password}>
                  {spinner('password') || <LockKeyhole size={16} strokeWidth={1.75} />} Sign in
                </button>
              </form>
            )}
            {methods.password && (passkeys || oauth) && <div className={styles.divider}><span>or</span></div>}
            <div className={styles.providers}>
              {passkeys && (
                <button type="button" className={`btn ${methods.password ? 'btn-secondary' : 'btn-primary'} ${styles.provider}`} disabled={!!busy}
                  onClick={() => run('passkey', () => api.signInWithPasskey())}>
                  {spinner('passkey') || <KeyRound size={16} strokeWidth={1.75} />} Sign in with a passkey
                </button>
              )}
              {oauth && (
                <div className={styles.providerRow} data-pair={(methods.github && methods.google) || undefined}>
                  {methods.github && (
                    <a className={`btn btn-secondary ${styles.provider}`} href={api.oauthUrl('github')}>
                      <GitHubLogo /> {methods.google ? 'GitHub' : 'Continue with GitHub'}
                    </a>
                  )}
                  {methods.google && (
                    <a className={`btn btn-secondary ${styles.provider}`} href={api.oauthUrl('google')}>
                      <GoogleLogo /> {methods.github ? 'Google' : 'Continue with Google'}
                    </a>
                  )}
                </div>
              )}
            </div>
            {(passkeys || oauth || methods.password) && methods.email && <div className={styles.divider}><span>or</span></div>}
            {methods.email && (
              <form onSubmit={sendCode} noValidate>
                <label className="field-label" htmlFor="signin-email">E-mail</label>
                <input id="signin-email" ref={inputRef} className="field" type="email" inputMode="email" autoComplete="email"
                  placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)}
                  aria-invalid={!!error} aria-describedby={error ? 'signin-error' : undefined} />
                <button type="submit" className={`btn btn-secondary ${styles.submit}`} disabled={!!busy}>
                  {spinner('email') || <Mail size={16} strokeWidth={1.75} />} E-mail me a sign-in code
                </button>
              </form>
            )}
            {(passkeys || oauth || methods.password) && (
              <div className={styles.row}>
                {canSignUp ? (
                  <button type="button" className={styles.link} onClick={() => go('signup')}>Create an account</button>
                ) : <span />}
                <button type="button" className={styles.link} onClick={() => go('recovery')}>
                  <LifeBuoy size={14} strokeWidth={1.75} /> Use a recovery code
                </button>
              </div>
            )}
            {!passkeys && !oauth && !methods.email && !methods.password && (
              <p className={styles.sub}>No sign-in method is available here yet. Ask the server's administrator.</p>
            )}
            {methods.demo && (
              <div className={styles.demo}>
                <div>
                  <strong>Just looking?</strong>
                  <span>Ask questions about a sample library. No account needed.</span>
                </div>
                <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => run('demo', () => api.startGuest())}>
                  {spinner('demo')} Try the demo <ArrowRight size={14} strokeWidth={1.75} />
                </button>
              </div>
            )}
          </>
        )}

        {step === 'signup' && (
          <>
            <h1 id="signin-title" className={styles.title}>Create your account</h1>
            <p className={styles.sub}>
              {signupWith === 'password'
                ? 'No e-mail needed. Choose a username and a password. You also get recovery codes, in case you forget the password.'
                : 'No password and no e-mail. A passkey on this device (Face ID, Touch ID, Windows Hello or your phone) is how you sign in.'}
            </p>
            {methods.password && passkeys && (
              <div className={styles.choice}>
                <Segmented label="How you sign in" stretch value={signupWith}
                  onChange={(v) => { setSignupWith(v); setError(null); }}
                  options={[
                    { value: 'password', label: 'Password', icon: LockKeyhole },
                    { value: 'passkey', label: 'Passkey', icon: KeyRound },
                  ]} />
              </div>
            )}
            {signupWith === 'password' && methods.password ? (
              <form className={styles.fields} onSubmit={signUpPassword} noValidate>
                <div>
                  <label className="field-label" htmlFor="signup-name">Your name <span className={styles.optional}>optional</span></label>
                  <input id="signup-name" ref={inputRef} className="field" autoComplete="name" maxLength={80} value={name}
                    onChange={(e) => setName(e.target.value)} placeholder="Shown on your account only" />
                </div>
                <div>
                  <label className="field-label" htmlFor="signup-username">Username</label>
                  <input id="signup-username" className="field" autoComplete="username" autoCapitalize="none" spellCheck={false}
                    maxLength={32} value={username} onChange={(e) => edit(setUsername)(e.target.value)}
                    aria-describedby="signup-username-hint" />
                  <p id="signup-username-hint" className={styles.fieldHint}>Letters, digits, dots, dashes or underscores. You sign in with it.</p>
                </div>
                <div>
                  <label className="field-label" htmlFor="signup-password">Password</label>
                  <PasswordInput id="signup-password" autoComplete="new-password" value={password} onChange={edit(setPassword)} />
                  <p className={styles.fieldHint} data-ok={password.length >= MIN_PASSWORD || undefined}>{passwordHint(password)}</p>
                </div>
                <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || !cleanName || !password}>
                  {spinner('signup')} Create account
                </button>
              </form>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); if (name.trim()) void run('signup', () => api.signUpWithPasskey(name.trim())); }} noValidate>
                <label className="field-label" htmlFor="signup-name">Your name</label>
                <input id="signup-name" ref={inputRef} className="field" autoComplete="name" maxLength={80} value={name}
                  onChange={(e) => setName(e.target.value)} placeholder="Shown on your account only" />
                <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || !name.trim()}>
                  {spinner('signup') || <KeyRound size={16} strokeWidth={1.75} />} Create a passkey
                </button>
              </form>
            )}
            <div className={styles.row}>{back('start', 'I already have an account')}</div>
          </>
        )}

        {step === 'codes' && (
          <>
            <h1 id="signin-title" className={styles.title}>Save your recovery codes</h1>
            <p className={styles.sub}>
              {pendingUser?.has_password
                ? 'If you forget your password, a recovery code lets you choose a new one.'
                : 'If you lose this device, a recovery code is how you get back in.'}{' '}
              Each code works once. Keep them somewhere safe, like a password manager. They are not shown again.
            </p>
            <RecoveryCodes codes={codes} />
            <label className={styles.check}>
              <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I have saved these codes
            </label>
            <button type="button" className={`btn btn-primary ${styles.submit}`} disabled={!saved}
              onClick={() => pendingUser && onSignedIn(pendingUser)}>
              Continue to OmniDoc
            </button>
          </>
        )}

        {step === 'recovery' && (
          <>
            <h1 id="signin-title" className={styles.title}>Use a recovery code</h1>
            <p className={styles.sub}>Lost your passkey? Enter one of the codes you saved when you made your account. It works once.</p>
            <form onSubmit={(e) => { e.preventDefault(); if (code.trim()) void run('recovery', () => api.signInWithRecoveryCode(code.trim())); }} noValidate>
              <label className="field-label" htmlFor="recovery-code">Recovery code</label>
              <input id="recovery-code" ref={inputRef} className={`field ${styles.mono}`} autoComplete="off" spellCheck={false}
                placeholder="xxxx-xxxx-xxxx" maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} />
              <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || code.trim().length < 12}>
                {spinner('recovery')} Sign in
              </button>
            </form>
            <p className={styles.hint}>After signing in, add a new passkey under Account so you are not left with codes alone.</p>
            <div className={styles.row}>{back()}</div>
          </>
        )}

        {step === 'reset' && (
          <>
            <h1 id="signin-title" className={styles.title}>Reset your password</h1>
            <p className={styles.sub}>
              OmniDoc never asks for an e-mail address, so the recovery codes you saved when you made the account are how
              you reset it. Each code works once.
            </p>
            <form className={styles.fields} onSubmit={resetWithCode} noValidate>
              <div>
                <label className="field-label" htmlFor="reset-username">Username</label>
                <input id="reset-username" ref={username ? undefined : inputRef} className="field" autoComplete="username"
                  autoCapitalize="none" spellCheck={false} maxLength={64} value={username} onChange={(e) => edit(setUsername)(e.target.value)} />
              </div>
              <div>
                <label className="field-label" htmlFor="reset-code">Recovery code</label>
                <input id="reset-code" ref={username ? inputRef : undefined} className={`field ${styles.mono}`} autoComplete="off"
                  spellCheck={false} placeholder="xxxx-xxxx-xxxx" maxLength={20} value={code} onChange={(e) => edit(setCode)(e.target.value)} />
              </div>
              <div>
                <label className="field-label" htmlFor="reset-password">New password</label>
                <PasswordInput id="reset-password" autoComplete="new-password" value={password} onChange={edit(setPassword)} />
                <p className={styles.fieldHint} data-ok={password.length >= MIN_PASSWORD || undefined}>{passwordHint(password)}</p>
              </div>
              <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || !cleanName || !code.trim() || !password}>
                {spinner('reset')} Reset and sign in
              </button>
            </form>
            <p className={styles.hint}>
              Your other devices are signed out. No codes left? A passkey, GitHub or Google sign-in still works if you added one.
            </p>
            <div className={styles.row}>{back('start', 'Back to sign in')}</div>
          </>
        )}

        {step === 'mfa' && (
          <>
            <h1 id="signin-title" className={styles.title}>Two-step sign-in</h1>
            <p className={styles.sub}>
              {useRecovery ? 'Enter one of your recovery codes. It works once.' : 'Enter the six-digit code from your authenticator app.'}
            </p>
            <form onSubmit={(e) => { e.preventDefault(); if (code) void verifyTwoStep(code.trim()); }} noValidate>
              <label className="field-label" htmlFor="mfa-code">{useRecovery ? 'Recovery code' : 'Code'}</label>
              {useRecovery ? (
                <input id="mfa-code" ref={inputRef} className={`field ${styles.mono}`} autoComplete="off" spellCheck={false}
                  placeholder="xxxx-xxxx-xxxx" maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} />
              ) : (
                <input id="mfa-code" ref={inputRef} className={`field ${styles.code}`} inputMode="numeric" autoComplete="one-time-code"
                  pattern="[0-9]*" maxLength={6} value={code} onChange={(e) => onDigits(e.target.value, verifyTwoStep)}
                  aria-invalid={!!error} aria-describedby={error ? 'signin-error' : undefined} />
              )}
              <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || (!useRecovery && code.length !== 6)}>
                {spinner('verify')} Continue
              </button>
            </form>
            <div className={styles.row}>
              {back('start', 'Start again')}
              <button type="button" className={styles.link} onClick={() => { setUseRecovery((v) => !v); setCode(''); setError(null); }}>
                {useRecovery ? 'Use the authenticator app' : 'Use a recovery code'}
              </button>
            </div>
          </>
        )}

        {step === 'code' && (
          <>
            <h1 id="signin-title" className={styles.title}>Check your e-mail</h1>
            <p className={styles.sub}>
              We sent a six-digit code to <strong>{email.trim()}</strong>. It expires in 10 minutes.
            </p>
            <form onSubmit={(e) => { e.preventDefault(); if (code.length === 6) void verifyEmail(code); }} noValidate>
              <label className="field-label" htmlFor="signin-code">Sign-in code</label>
              <input id="signin-code" ref={inputRef} className={`field ${styles.code}`} inputMode="numeric" autoComplete="one-time-code"
                pattern="[0-9]*" maxLength={6} value={code} onChange={(e) => onDigits(e.target.value, verifyEmail)}
                aria-invalid={!!error} aria-describedby={error ? 'signin-error' : undefined} />
              <button type="submit" className={`btn btn-primary ${styles.submit}`} disabled={!!busy || code.length !== 6}>
                {spinner('verify')} Sign in
              </button>
            </form>
            <div className={styles.row}>
              {back('start', 'Use another address')}
              <button type="button" className={styles.link} disabled={wait > 0 || !!busy} onClick={() => void sendCode()}>
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
      <p className={styles.footnote}>
        OmniDoc keeps your name, how you sign in, and your own documents and conversations. Nothing else about you is collected.
      </p>
    </main>
  );
}
