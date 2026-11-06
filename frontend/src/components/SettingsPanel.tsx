import { useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Bell, Download, ExternalLink, KeyRound, LogOut, RotateCcw, ShieldUser, Sparkles, Trash2, UserRound, X } from 'lucide-react';
import { api } from '../api';
import type { User } from '../api';
import { setThemePreference } from '../lib/theme';
import { isMac, resetSettings, setSetting, useSettings } from '../lib/settings';
import type { Accent, Backdrop, Density, MotionPreference, Navigation, SendKey, TextSize } from '../lib/settings';
import { SUPPORTED_LANGUAGES } from '../utils/voice';
import { ThemeSwitch } from './ThemeSwitch';
import { EffortChoice, ModelChoices } from './ModelPicker';
import type { CostContext } from './ModelPicker';
import { Segmented, Toggle } from './ui/Controls';
import { useToast } from './ui/Toast';
import styles from './SettingsPanel.module.css';

const REPO = 'https://github.com/muditagrawal-alt/OmniDoc';

const ACCENTS: Array<{ value: Accent; label: string; swatch: string }> = [
  { value: 'blue', label: 'Blue', swatch: '#0f62fe' },
  { value: 'teal', label: 'Teal', swatch: '#007d79' },
  { value: 'violet', label: 'Violet', swatch: '#8a3ffc' },
  { value: 'magenta', label: 'Magenta', swatch: '#d02670' },
  { value: 'orange', label: 'Orange', swatch: '#ba4e00' },
];

const SECTIONS = [
  { id: 'appearance', label: 'Appearance' },
  { id: 'answers', label: 'Answers' },
  { id: 'chat', label: 'Chat' },
  { id: 'account', label: 'Account' },
  { id: 'data', label: 'Data' },
  { id: 'shortcuts', label: 'Shortcuts' },
  { id: 'about', label: 'About' },
];

interface SettingsPanelProps extends CostContext {
  open: boolean;
  onClose: () => void;
  user: User | null;
  isMobile: boolean;
  /** "Your own model key" on a hosted server; the free model APIs dialog on a local install. */
  onOpenKeys: () => void;
  onOpenAccount: () => void;
  onOpenNotices: () => void;
  unreadNotices: number;
  onSignOut: () => void;
  onOpenProfile: () => void;
  /** Opens the Admin page: the overview for an administrator, the setup-code form for anyone else. */
  onOpenAdmin: () => void;
  chatCount: number;
  onClearChats: () => Promise<void>;
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={`settings-${id}`} className={styles.section} aria-labelledby={`settings-${id}-title`}>
      <h3 id={`settings-${id}-title`}>{title}</h3>
      {children}
    </section>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <div className={styles.fieldText}>
        <span>{label}</span>
        {hint && <small>{hint}</small>}
      </div>
      {children}
    </div>
  );
}

/** Every preference in one panel beside the navigation: appearance, answers, chat, account, data. */
export function SettingsPanel(props: SettingsPanelProps) {
  const { open, onClose, user, isMobile, accountsMode, chatCount } = props;
  const s = useSettings();
  const toast = useToast();
  const panelRef = useRef<HTMLElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [exporting, setExporting] = useState(false);
  const guest = user?.kind === 'guest';
  const mod = isMac ? '⌘' : 'Ctrl';

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusables = () =>
      Array.from(panel?.querySelectorAll<HTMLElement>('button, [href], input, select, [tabindex]:not([tabindex="-1"])') ?? [])
        .filter((el) => !el.hasAttribute('disabled'));
    focusables()[0]?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'Tab') {
        const items = focusables();
        if (!items.length) return;
        if (e.shiftKey && document.activeElement === items[0]) {
          e.preventDefault();
          items[items.length - 1].focus();
        } else if (!e.shiftKey && document.activeElement === items[items.length - 1]) {
          e.preventDefault();
          items[0].focus();
        }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      previous?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  const jump = (id: string) => {
    const target = document.getElementById(`settings-${id}`);
    if (target && bodyRef.current) bodyRef.current.scrollTo({ top: target.offsetTop - 8, behavior: 'smooth' });
  };

  const clearChats = async () => {
    setClearing(true);
    try {
      await props.onClearChats();
      toast('All conversations were deleted', 'good');
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setClearing(false);
      setConfirmClear(false);
    }
  };

  const exportAll = async () => {
    setExporting(true);
    try {
      await api.exportAccount();
    } catch (e) {
      toast((e as Error).message, 'bad');
    } finally {
      setExporting(false);
    }
  };

  const reset = () => {
    resetSettings();
    setThemePreference('system');
    toast('Settings are back to their defaults');
  };

  return createPortal(
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={panelRef} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header className={styles.header}>
          <h2 id={titleId}>Settings</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close settings">
            <X size={18} strokeWidth={1.75} />
          </button>
        </header>
        <nav className={styles.index} aria-label="Settings sections">
          {SECTIONS.map((x) => (
            <button key={x.id} type="button" className="chip" onClick={() => jump(x.id)}>{x.label}</button>
          ))}
        </nav>

        <div ref={bodyRef} className={styles.body}>
          <Section id="appearance" title="Appearance">
            <Field label="Theme" hint="System follows this device’s light or dark setting.">
              <ThemeSwitch labelled stretch />
            </Field>
            <Field label="Accent colour">
              <div role="radiogroup" aria-label="Accent colour" className={styles.swatches}>
                {ACCENTS.map((a) => (
                  <button key={a.value} type="button" role="radio" aria-checked={s.accent === a.value} aria-label={a.label}
                    title={a.label} className={styles.swatch} style={{ background: a.swatch }}
                    onClick={() => setSetting('accent', a.value)} />
                ))}
              </div>
            </Field>
            <Field label="Text size">
              <Segmented<TextSize> stretch label="Text size" value={s.textSize} onChange={(v) => setSetting('textSize', v)}
                options={[{ value: 'small', label: 'Small' }, { value: 'default', label: 'Default' }, { value: 'large', label: 'Large' }]} />
            </Field>
            <Field label="Density" hint="Compact fits more on the screen.">
              <Segmented<Density> stretch label="Density" value={s.density} onChange={(v) => setSetting('density', v)}
                options={[{ value: 'comfortable', label: 'Comfortable' }, { value: 'compact', label: 'Compact' }]} />
            </Field>
            <Field label="Motion" hint="Reduce turns off animations; System follows the device setting.">
              <Segmented<MotionPreference> stretch label="Motion" value={s.motion} onChange={(v) => setSetting('motion', v)}
                options={[{ value: 'system', label: 'System' }, { value: 'reduce', label: 'Reduce' }, { value: 'full', label: 'Full' }]} />
            </Field>
            <Field label="Chat background" hint="Rings of dust drifting out from behind the conversation.">
              <Segmented<Backdrop> stretch label="Chat background" value={s.backdrop} onChange={(v) => setSetting('backdrop', v)}
                options={[{ value: 'animated', label: 'Moving' }, { value: 'still', label: 'Still' }, { value: 'off', label: 'Off' }]} />
            </Field>
            {!isMobile && (
              <Field label="Navigation" hint="The icon rail opens lists on hover; the full sidebar keeps your chats in view.">
                <Segmented<Navigation> stretch label="Navigation" value={s.navigation} onChange={(v) => setSetting('navigation', v)}
                  options={[{ value: 'rail', label: 'Icon rail' }, { value: 'sidebar', label: 'Full sidebar' }]} />
              </Field>
            )}
          </Section>

          <Section id="answers" title="Answers">
            <Field label="Model" hint="Used for every answer from now on.">
              <div className={styles.box}><ModelChoices /></div>
            </Field>
            <Field label="Effort">
              <EffortChoice />
            </Field>
            <Field label="Web search" hint="Auto searches the web only when your documents do not answer the question.">
              <Segmented stretch label="Web search" value={s.webMode} onChange={(v) => setSetting('webMode', v)}
                options={[{ value: 'auto', label: 'Auto' }, { value: 'on', label: 'Always' }, { value: 'off', label: 'Never' }]} />
            </Field>
            <Field label="Answer language" hint="You can also change it for one question in the question box.">
              <select className={`field ${styles.select}`} value={s.language} onChange={(e) => setSetting('language', e.target.value)}
                aria-label="Answer language">
                {SUPPORTED_LANGUAGES.map((l) => (
                  <option key={l.code} value={l.code}>{l.name}{l.nativeName !== l.name ? ` (${l.nativeName})` : ''}</option>
                ))}
              </select>
            </Field>
            <Toggle label="Show the steps" description="Open the list of what was done under every answer."
              checked={s.showSteps} onChange={(v) => setSetting('showSteps', v)} />
            <Toggle label="Show the sentence checks" description="Open the check of each sentence against its source."
              checked={s.showChecks} onChange={(v) => setSetting('showChecks', v)} />
            <button type="button" className={`btn btn-secondary ${styles.wide}`} onClick={() => { onClose(); props.onOpenKeys(); }}>
              {accountsMode ? <KeyRound size={15} strokeWidth={1.75} /> : <Sparkles size={15} strokeWidth={1.75} />}
              {accountsMode ? 'Your own model key…' : 'Free model APIs and web search…'}
            </button>
          </Section>

          <Section id="chat" title="Chat">
            <Field label="Send with" hint="The other key adds a new line.">
              <Segmented<SendKey> stretch label="Send with" value={s.sendKey} onChange={(v) => setSetting('sendKey', v)}
                options={[{ value: 'enter', label: 'Enter' }, { value: 'mod-enter', label: `${mod} + Enter` }]} />
            </Field>
          </Section>

          <Section id="account" title="Account">
            {user && <p className={styles.who}>{guest ? 'You are exploring the demo.' : `Signed in as ${user.email || user.name}.`}</p>}
            <div className={styles.actions}>
              {accountsMode && user && (
                <button type="button" className="btn btn-secondary" onClick={() => { onClose(); props.onOpenAccount(); }}>
                  <UserRound size={15} strokeWidth={1.75} /> {guest ? 'About the demo…' : 'Account and security…'}
                </button>
              )}
              {accountsMode && user && !guest && (
                <button type="button" className="btn btn-secondary" onClick={() => { onClose(); props.onOpenNotices(); }}>
                  <Bell size={15} strokeWidth={1.75} /> Notifications{props.unreadNotices > 0 ? ` (${props.unreadNotices} new)` : ''}
                </button>
              )}
              {accountsMode && user && !guest && (
                <button type="button" className="btn btn-secondary" onClick={() => { onClose(); props.onOpenAdmin(); }}>
                  <ShieldUser size={15} strokeWidth={1.75} /> {user.admin ? 'Admin' : 'Administer this server…'}
                </button>
              )}
              {!accountsMode && !user && (
                <button type="button" className="btn btn-secondary" onClick={() => { onClose(); props.onOpenProfile(); }}>
                  <UserRound size={15} strokeWidth={1.75} /> Create a local profile
                </button>
              )}
              {user && (
                <button type="button" className="btn btn-secondary" onClick={() => { onClose(); props.onSignOut(); }}>
                  <LogOut size={15} strokeWidth={1.75} /> {guest ? 'Leave the demo' : 'Sign out'}
                </button>
              )}
            </div>
          </Section>

          <Section id="data" title="Data">
            <div className={styles.actions}>
              {accountsMode && user && !guest && (
                <button type="button" className="btn btn-secondary" onClick={exportAll} disabled={exporting}>
                  {exporting ? <span className="spinner" /> : <Download size={15} strokeWidth={1.75} />} Download everything (.zip)
                </button>
              )}
              {!guest && chatCount > 0 && !confirmClear && (
                <button type="button" className="btn btn-secondary" onClick={() => setConfirmClear(true)}>
                  <Trash2 size={15} strokeWidth={1.75} /> Delete all conversations
                </button>
              )}
              <button type="button" className="btn btn-secondary" onClick={reset}>
                <RotateCcw size={15} strokeWidth={1.75} /> Reset settings
              </button>
            </div>
            {confirmClear && (
              <div className={styles.confirm} role="alert">
                <p>Delete all {chatCount} {chatCount === 1 ? 'conversation' : 'conversations'}? Your documents stay. This cannot be undone.</p>
                <div className={styles.actions}>
                  <button type="button" className="btn btn-danger" onClick={clearChats} disabled={clearing}>
                    {clearing && <span className="spinner" />} Delete all
                  </button>
                  <button type="button" className="btn btn-ghost" onClick={() => setConfirmClear(false)}>Cancel</button>
                </div>
              </div>
            )}
            <p className={styles.note}>Settings are kept in this browser only.</p>
          </Section>

          <Section id="shortcuts" title="Keyboard shortcuts">
            <dl className={styles.keys}>
              <div><dt>New chat</dt><dd><kbd className="kbd">{mod}</kbd><kbd className="kbd">⇧</kbd><kbd className="kbd">O</kbd></dd></div>
              <div><dt>Search the library</dt><dd><kbd className="kbd">{mod}</kbd><kbd className="kbd">K</kbd></dd></div>
              <div><dt>Settings</dt><dd><kbd className="kbd">{mod}</kbd><kbd className="kbd">,</kbd></dd></div>
              <div>
                <dt>Send</dt>
                <dd>{s.sendKey === 'enter' ? <kbd className="kbd">Enter</kbd> : <><kbd className="kbd">{mod}</kbd><kbd className="kbd">Enter</kbd></>}</dd>
              </div>
              <div><dt>New line</dt><dd><kbd className="kbd">⇧</kbd><kbd className="kbd">Enter</kbd></dd></div>
              <div><dt>Close a panel or menu</dt><dd><kbd className="kbd">Esc</kbd></dd></div>
            </dl>
          </Section>

          <Section id="about" title="About">
            <p className={styles.note}>
              OmniDoc is open source under the MIT licence. Answers come from free models, and every claim links to the page
              it came from.
            </p>
            <div className={styles.actions}>
              <a className="btn btn-secondary" href={REPO} target="_blank" rel="noreferrer">
                <ExternalLink size={15} strokeWidth={1.75} /> Source code
              </a>
              <a className="btn btn-secondary" href={`${REPO}/tree/main/benchmarks`} target="_blank" rel="noreferrer">
                <ExternalLink size={15} strokeWidth={1.75} /> Benchmarks
              </a>
            </div>
          </Section>
        </div>
      </aside>
    </div>,
    document.body,
  );
}
