import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cx } from '../../lib/cx';

export interface TabDef<T extends string> {
  id: T;
  label: ReactNode;
}

function tabId(prefix: string, id: string) {
  return `${prefix}-tab-${id}`;
}

function panelId(prefix: string, id: string) {
  return `${prefix}-panel-${id}`;
}

/** WAI-ARIA tabs with roving tabindex; arrow keys, Home and End move between tabs. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
  label,
  idPrefix,
  className,
}: {
  tabs: Array<TabDef<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  idPrefix: string;
  className?: string;
}) {
  const refs = useRef(new Map<string, HTMLButtonElement>());

  const focusTab = (index: number) => {
    const tab = tabs[(index + tabs.length) % tabs.length];
    if (!tab) return;
    onChange(tab.id);
    refs.current.get(tab.id)?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    switch (event.key) {
      case 'ArrowRight':
        event.preventDefault();
        focusTab(index + 1);
        break;
      case 'ArrowLeft':
        event.preventDefault();
        focusTab(index - 1);
        break;
      case 'Home':
        event.preventDefault();
        focusTab(0);
        break;
      case 'End':
        event.preventDefault();
        focusTab(tabs.length - 1);
        break;
      default:
    }
  };

  return (
    <div
      role="tablist"
      aria-label={label}
      className={cx(
        'inline-flex max-w-full gap-1 overflow-x-auto rounded-2xl border border-line bg-surface-muted p-1',
        className,
      )}
    >
      {tabs.map((tab, index) => {
        const selected = tab.id === value;
        return (
          <button
            key={tab.id}
            ref={(node) => {
              if (node) refs.current.set(tab.id, node);
              else refs.current.delete(tab.id);
            }}
            type="button"
            role="tab"
            id={tabId(idPrefix, tab.id)}
            aria-selected={selected}
            aria-controls={panelId(idPrefix, tab.id)}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(tab.id)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cx(
              'inline-flex h-9 items-center gap-2 whitespace-nowrap rounded-xl px-4 text-sm font-medium transition-colors',
              selected
                ? 'bg-raised text-ink shadow-sm ring-1 ring-black/5 dark:bg-white/10 dark:ring-white/10'
                : 'text-muted hover:text-ink',
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  idPrefix,
  id,
  children,
  className,
}: {
  idPrefix: string;
  id: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role="tabpanel"
      id={panelId(idPrefix, id)}
      aria-labelledby={tabId(idPrefix, id)}
      tabIndex={0}
      className={cx('focus-visible:outline-offset-4', className)}
    >
      {children}
    </div>
  );
}
