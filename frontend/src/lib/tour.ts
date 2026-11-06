import { useSyncExternalStore } from 'react';
import { isMac } from './settings';

/*
 * The guided tour of the workspace (components/Tour.tsx). Each step points at an element marked
 * data-tour="<target>"; steps whose element is not on screen (the other navigation layout, a
 * phone, an administrator-only item) are left out. It opens once on its own for each account in
 * a browser, and again whenever startTour() is called (Settings, the profile menu).
 */

export interface TourStep {
  id: string;
  /** data-tour value of the element to point at; none for the opening and closing cards. */
  target?: string;
  title: string;
  body: string;
}

const mod = isMac ? '⌘' : 'Ctrl+';

export const TOUR_STEPS: TourStep[] = [
  { id: 'welcome', title: 'Welcome to OmniDoc', body: 'A one-minute look around. Use the arrow keys or the buttons; Esc leaves, and Settings has the tour whenever you want it again.' },
  { id: 'composer', target: 'composer', title: 'Ask your documents', body: 'Ask in plain words, in any of ten languages. Every claim in the answer cites its page, and every sentence is checked against its source.' },
  { id: 'attach', target: 'attach', title: 'Add documents', body: 'PDFs, scans and photos (read with OCR), Word, spreadsheets, slides, e-mail and recordings. You can also drop files onto the chat.' },
  { id: 'model', target: 'model', title: 'Model and effort', body: 'Pick the model that answers you and how hard it works: Quick, Balanced or Thorough. Free models are marked.' },
  { id: 'new-chat', target: 'new-chat', title: 'Start fresh', body: `A new conversation, any time (${mod}⇧O). Earlier chats are kept, with a summary of older turns so follow-ups can refer back.` },
  { id: 'chats', target: 'chats', title: 'Your conversations', body: 'Hover to see recent chats; rename or delete them from here.' },
  { id: 'search', target: 'search', title: 'Search every passage', body: `Find the exact passage across the whole library (${mod}K), then ask about it in one click.` },
  { id: 'library', target: 'library', title: 'Your library', body: 'Every document with its pages, summary and fields. Click a citation in an answer and the document opens at that sentence.' },
  { id: 'tools', target: 'tools', title: 'Tools for the whole library', body: 'Extract fields into a table, compare two versions, browse every table, record and date, scan for personal data, and explore the knowledge globe.' },
  { id: 'connect', target: 'connect', title: 'Bring your assistant', body: 'Use your library from Claude Code, Claude Desktop or Cursor through OmniDoc’s MCP server.' },
  { id: 'admin', target: 'admin', title: 'Run the server', body: 'Usage, health and memory, the default model for everyone, feedback, and announcements.' },
  { id: 'notices', target: 'notices', title: 'Notifications', body: 'Sign-ins from new devices, finished uploads and what is new in OmniDoc.' },
  { id: 'settings', target: 'settings', title: 'Make it yours', body: `Theme, accent colour, text size, density, motion, backgrounds and how answers are shown (${mod},).` },
  { id: 'account', target: 'account', title: 'Your account', body: 'Password, passkeys, two-step sign-in, recovery codes, signed-in devices, and a download of everything.' },
  { id: 'done', title: 'You are all set', body: 'Ask your first question below. The tour is in Settings whenever you want it again.' },
];

const SEEN = 'omnidoc_tour_seen:';
let open = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function startTour() {
  open = true;
  emit();
}

export function endTour(userKey: string) {
  open = false;
  try {
    localStorage.setItem(SEEN + userKey, '1');
  } catch {
    /* storage refused: the tour may show again next time */
  }
  emit();
}

export function tourSeen(userKey: string) {
  try {
    return localStorage.getItem(SEEN + userKey) === '1';
  } catch {
    return true; // no storage: do not open it on every visit
  }
}

export function useTourOpen() {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => open,
    () => false,
  );
}

/** The element a step points at, when it is on screen and has a size. */
export function tourTarget(target: string): HTMLElement | null {
  const nodes = document.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`);
  for (const node of nodes) {
    const rect = node.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < window.innerWidth
        && rect.bottom > 0 && rect.top < window.innerHeight) return node;
  }
  return null;
}
