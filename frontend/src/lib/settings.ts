import { useSyncExternalStore } from 'react';
import type { Effort, WebMode } from '../api';

/*
 * Personal preferences, kept in this browser only. The ones that change how the whole page looks
 * (accent, text size, density, motion) are applied as data attributes on <html>, where
 * styles/preferences.css picks them up; the rest are read by the components that use them.
 */

export type Accent = 'blue' | 'teal' | 'violet' | 'magenta' | 'orange';
export type TextSize = 'small' | 'default' | 'large';
export type Density = 'comfortable' | 'compact';
export type MotionPreference = 'system' | 'reduce' | 'full';
export type Backdrop = 'animated' | 'still' | 'off';
export type SendKey = 'enter' | 'mod-enter';
export type Navigation = 'rail' | 'sidebar';

export interface Settings {
  accent: Accent;
  textSize: TextSize;
  density: Density;
  motion: MotionPreference;
  /** The drifting rings behind the chat. */
  backdrop: Backdrop;
  effort: Effort;
  /** The answer model for this user's questions ("provider:model"); empty: the server's default. */
  model: string;
  webMode: WebMode;
  /** Default answer language (a code from utils/voice SUPPORTED_LANGUAGES). */
  language: string;
  sendKey: SendKey;
  /** Desktop navigation: an icon rail with flyouts, or the full sidebar with the chat list. */
  navigation: Navigation;
  /** Open the "Worked for…" list of steps under every answer. */
  showSteps: boolean;
  /** Open the sentence checks under every answer. */
  showChecks: boolean;
}

export const DEFAULTS: Settings = {
  accent: 'blue',
  textSize: 'default',
  density: 'comfortable',
  motion: 'system',
  backdrop: 'animated',
  effort: 'balanced',
  model: '',
  webMode: 'auto',
  language: 'en',
  sendKey: 'enter',
  navigation: 'rail',
  showSteps: false,
  showChecks: false,
};

const STORAGE_KEY = 'omnidoc_settings';
const OPTIONS: { [K in keyof Settings]?: readonly Settings[K][] } = {
  accent: ['blue', 'teal', 'violet', 'magenta', 'orange'],
  textSize: ['small', 'default', 'large'],
  density: ['comfortable', 'compact'],
  motion: ['system', 'reduce', 'full'],
  backdrop: ['animated', 'still', 'off'],
  effort: ['quick', 'balanced', 'thorough'],
  webMode: ['auto', 'on', 'off'],
  sendKey: ['enter', 'mod-enter'],
  navigation: ['rail', 'sidebar'],
};

function read(): Settings {
  const out: Settings = { ...DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}') as Partial<Record<keyof Settings, unknown>>;
    for (const key of Object.keys(DEFAULTS) as Array<keyof Settings>) {
      const value = raw[key];
      const allowed = OPTIONS[key] as readonly unknown[] | undefined;
      if (allowed ? allowed.includes(value) : typeof value === typeof DEFAULTS[key]) {
        (out as unknown as Record<string, unknown>)[key] = value;
      }
    }
    // Web search used to have a key of its own.
    const legacyWeb = localStorage.getItem('omnidoc_web_mode');
    if (raw.webMode === undefined && (legacyWeb === 'on' || legacyWeb === 'off')) out.webMode = legacyWeb;
  } catch {
    /* storage unavailable or unreadable: defaults */
  }
  return out;
}

let current: Settings = read();
const listeners = new Set<() => void>();

function applyToPage(s: Settings) {
  const root = document.documentElement;
  root.dataset.accent = s.accent;
  root.dataset.textSize = s.textSize;
  root.dataset.density = s.density;
  root.dataset.motion = s.motion;
}

applyToPage(current);

export function setSetting<K extends keyof Settings>(key: K, value: Settings[K]) {
  if (current[key] === value) return;
  current = { ...current, [key]: value };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    /* storage unavailable: the change lasts until the page is reloaded */
  }
  applyToPage(current);
  listeners.forEach((l) => l());
}

export function resetSettings() {
  current = { ...DEFAULTS };
  try {
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem('omnidoc_web_mode');
  } catch {
    /* storage unavailable */
  }
  applyToPage(current);
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** The current preferences, outside React. */
export function getSettings(): Settings {
  return current;
}

/** The current preferences; components re-render when one changes. */
export function useSettings(): Settings {
  return useSyncExternalStore(subscribe, () => current);
}

/** True when animation should stop: the user's choice here, or the system setting when they left it to the system. */
export function prefersStill(s: Settings): boolean {
  if (s.motion === 'reduce') return true;
  if (s.motion === 'full') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** True on Mac-style keyboards, where the command key is shown as ⌘. */
export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
