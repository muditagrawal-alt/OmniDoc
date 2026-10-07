import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import styles from './ui.module.css';

interface MenuProps {
  /** Renders the trigger; spread the props onto a <button>. */
  trigger: (props: {
    'aria-haspopup': 'menu';
    'aria-expanded': boolean;
    'aria-controls': string;
    onClick: () => void;
    ref: (el: HTMLButtonElement | null) => void;
  }) => ReactNode;
  children: (close: () => void) => ReactNode;
  align?: 'start' | 'end';
  side?: 'top' | 'bottom';
  label: string;
}

/** Accessible popover menu: Esc / outside click close, arrow keys move focus. */
export function Menu({ trigger, children, align = 'end', side = 'bottom', label }: MenuProps) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const close = useCallback(() => {
    setOpen(false);
    triggerRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!panelRef.current?.contains(t) && !triggerRef.current?.contains(t)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
        return;
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
      const items = Array.from(panelRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not([disabled])') ?? []);
      if (!items.length) return;
      e.preventDefault();
      const i = items.indexOf(document.activeElement as HTMLElement);
      const next = e.key === 'ArrowDown' ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
      items[next].focus();
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    const first = panelRef.current?.querySelector<HTMLElement>('[role^="menuitem"]');
    first?.focus();
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, close]);

  return (
    <div className={styles.menuRoot}>
      {trigger({
        'aria-haspopup': 'menu',
        'aria-expanded': open,
        'aria-controls': id,
        onClick: () => setOpen((o) => !o),
        ref: (el) => {
          triggerRef.current = el;
        },
      })}
      {open && (
        <div
          ref={panelRef}
          id={id}
          role="menu"
          aria-label={label}
          className={`surface-menu ${styles.menuPanel}`}
          data-align={align}
          data-side={side}
        >
          {children(close)}
        </div>
      )}
    </div>
  );
}
