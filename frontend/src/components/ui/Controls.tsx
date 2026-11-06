import { useCallback, useEffect, useId, useRef, useState } from 'react';
import type { ComponentType, KeyboardEvent, ReactNode } from 'react';
import styles from './Controls.module.css';

type IconType = ComponentType<{ size?: number; strokeWidth?: number }>;

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  icon?: IconType;
  /** Shown as the tooltip. */
  hint?: string;
}

interface SegmentedProps<T extends string> {
  options: ReadonlyArray<SegmentedOption<T>>;
  value: T;
  onChange: (value: T) => void;
  label: string;
  /** Icons only, with the label as tooltip and accessible name (needs an icon on every option). */
  iconOnly?: boolean;
  size?: 'sm' | 'md';
  stretch?: boolean;
}

/** A row of mutually exclusive choices (radio group): click, or arrow keys once focused. */
export function Segmented<T extends string>({ options, value, onChange, label, iconOnly = false, size = 'md', stretch = false }: SegmentedProps<T>) {
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key)) return;
    e.preventDefault();
    const i = options.findIndex((o) => o.value === value);
    const step = e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 1;
    const next = options[(i + step + options.length) % options.length];
    onChange(next.value);
    const group = e.currentTarget;
    requestAnimationFrame(() => group.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };
  return (
    <div role="radiogroup" aria-label={label} className={styles.segmented} data-size={size} data-stretch={stretch || undefined}
      onKeyDown={onKeyDown}>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <button key={o.value} type="button" role="radio" aria-checked={selected} tabIndex={selected ? 0 : -1}
            className={styles.segment} title={iconOnly ? o.label : o.hint} aria-label={iconOnly ? o.label : undefined}
            onClick={() => onChange(o.value)}>
            {o.icon && <o.icon size={size === 'sm' ? 14 : 15} strokeWidth={1.75} />}
            {!iconOnly && <span>{o.label}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** An on/off switch with its label and an optional explanation. */
export function Toggle({ checked, onChange, label, description }: {
  checked: boolean; onChange: (checked: boolean) => void; label: string; description?: string;
}) {
  const id = useId();
  return (
    <div className={styles.toggleRow}>
      <div className={styles.toggleText}>
        <label htmlFor={id}>{label}</label>
        {description && <span>{description}</span>}
      </div>
      <button id={id} type="button" role="switch" aria-checked={checked} className={styles.switch} onClick={() => onChange(!checked)}>
        <span className={styles.knob} />
      </button>
    </div>
  );
}

interface PopoverProps {
  trigger: (props: {
    'aria-haspopup': 'dialog';
    'aria-expanded': boolean;
    'aria-controls': string;
    onClick: () => void;
    ref: (el: HTMLButtonElement | null) => void;
  }) => ReactNode;
  children: (close: () => void) => ReactNode;
  label: string;
  align?: 'start' | 'end';
  side?: 'top' | 'bottom';
  width?: number;
}

/** A panel anchored to its trigger for richer choices than a menu: Esc or a click outside closes it. */
export function Popover({ trigger, children, label, align = 'end', side = 'bottom', width = 340 }: PopoverProps) {
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
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      }
    };
    document.addEventListener('pointerdown', onPointer);
    document.addEventListener('keydown', onKey);
    panelRef.current?.querySelector<HTMLElement>('[aria-checked="true"], button, [href], input')?.focus();
    return () => {
      document.removeEventListener('pointerdown', onPointer);
      document.removeEventListener('keydown', onKey);
    };
  }, [open, close]);

  return (
    <div className={styles.popoverRoot}>
      {trigger({
        'aria-haspopup': 'dialog',
        'aria-expanded': open,
        'aria-controls': id,
        onClick: () => setOpen((o) => !o),
        ref: (el) => {
          triggerRef.current = el;
        },
      })}
      {open && (
        <div ref={panelRef} id={id} role="dialog" aria-label={label} className={styles.popover}
          data-align={align} data-side={side} style={{ width }}>
          {children(close)}
        </div>
      )}
    </div>
  );
}
