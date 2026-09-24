import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { InfoIcon } from './icons';

/**
 * An info button with a tooltip that opens on hover, focus or tap and closes
 * with Escape. The tooltip text is always in the DOM (hidden when closed) so
 * aria-describedby works for screen readers.
 */
export function InfoTip({
  label,
  children,
  className,
  placement = 'top',
}: {
  /** Accessible name of the button, e.g. "About the Shannon index". */
  label: string;
  children: ReactNode;
  className?: string;
  placement?: 'top' | 'bottom';
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [shift, setShift] = useState(0);
  const tipRef = useRef<HTMLSpanElement>(null);
  const wrapRef = useRef<HTMLSpanElement>(null);

  // Keep the bubble inside the viewport horizontally.
  useLayoutEffect(() => {
    if (!open) {
      setShift(0);
      return;
    }
    const tip = tipRef.current;
    if (!tip || typeof window === 'undefined') return;
    const rect = tip.getBoundingClientRect();
    const margin = 12;
    const viewport = document.documentElement.clientWidth || window.innerWidth;
    if (rect.left < margin) setShift(margin - rect.left);
    else if (rect.right > viewport - margin) setShift(viewport - margin - rect.right);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  return (
    <span
      ref={wrapRef}
      className={cx('relative inline-flex align-middle', className)}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        aria-expanded={open}
        className="inline-flex h-5 w-5 items-center justify-center rounded-full text-subtle transition-colors hover:text-ink"
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === 'Escape') setOpen(false);
        }}
      >
        <InfoIcon size={14} />
      </button>
      <span
        ref={tipRef}
        id={id}
        role="tooltip"
        hidden={!open}
        style={{ transform: `translateX(calc(-50% + ${shift}px))` }}
        className={cx(
          'absolute left-1/2 z-40 w-64 max-w-[calc(100vw-1.5rem)] rounded-xl border border-line bg-raised px-3 py-2.5 text-left text-xs font-normal normal-case leading-relaxed tracking-normal text-ink shadow-lift',
          placement === 'top' ? 'bottom-full mb-2' : 'top-full mt-2',
        )}
      >
        {children}
      </span>
    </span>
  );
}
