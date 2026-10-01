import { useId, useState } from 'react';
import type { Site } from '../../api/generated';
import { cx } from '../../lib/cx';
import { daysBetween, longDate, type Period, type PeriodPreset } from '../../lib/dates';
import { Button } from '../ui/Button';
import { Select } from './primitives';

const PRESETS: Array<{ value: PeriodPreset; label: string }> = [
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
  { value: 'custom', label: 'Custom' },
];

/** Period presets as rows, custom range behind the last option. */
export function PeriodPicker({
  period,
  onChange,
}: {
  period: Period;
  onChange: (next: { preset: PeriodPreset; from?: string; to?: string }) => void;
}) {
  const id = useId();
  const [draft, setDraft] = useState({ from: period.from, to: period.to });
  const [customOpen, setCustomOpen] = useState(period.preset === 'custom');

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Period"
        className="scrollbar-thin inline-flex max-w-full overflow-x-auto rounded-xl border border-line bg-surface-muted p-0.5"
      >
        {PRESETS.map((p) => {
          const selected = period.preset === p.value;
          return (
            <button
              key={p.value}
              type="button"
              aria-pressed={selected}
              onClick={() => {
                if (p.value === 'custom') {
                  setCustomOpen(true);
                  return;
                }
                setCustomOpen(false);
                onChange({ preset: p.value });
              }}
              className={cx(
                'h-8 shrink-0 whitespace-nowrap rounded-[0.6rem] px-3 text-[0.8125rem] font-medium transition-colors',
                selected
                  ? 'bg-raised text-ink shadow-sm ring-1 ring-black/5 dark:bg-white/10 dark:ring-white/10'
                  : 'text-muted hover:text-ink',
              )}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      {customOpen ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.from && draft.to && draft.from <= draft.to) {
              onChange({ preset: 'custom', from: draft.from, to: draft.to });
            }
          }}
        >
          <label className="text-xs text-muted">
            From
            <input
              id={`${id}-from`}
              type="date"
              className="field-input mt-0.5 h-8 w-40 py-1"
              value={draft.from}
              max={draft.to}
              onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))}
            />
          </label>
          <label className="text-xs text-muted">
            To
            <input
              id={`${id}-to`}
              type="date"
              className="field-input mt-0.5 h-8 w-40 py-1"
              value={draft.to}
              min={draft.from}
              onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
            />
          </label>
          <Button type="submit" size="sm" variant="secondary">
            Apply
          </Button>
        </form>
      ) : null}
      <span className="text-xs text-muted" data-testid="period-summary">
        {longDate(period.from)} to {longDate(period.to)} ({daysBetween(period.from, period.to)}{' '}
        days)
      </span>
    </div>
  );
}

export function SiteSelect({
  sites,
  value,
  onChange,
  allLabel = 'All sites',
  label = 'Site',
  id,
}: {
  sites: Site[];
  value: string | null;
  onChange: (siteId: string | null) => void;
  allLabel?: string | null;
  label?: string;
  id?: string;
}) {
  const auto = useId();
  const selectId = id ?? auto;
  return (
    <label htmlFor={selectId} className="flex items-center gap-2 text-xs text-muted">
      {label}
      <Select
        id={selectId}
        className="h-8 w-auto min-w-[10rem] py-1"
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
      >
        {allLabel !== null ? <option value="">{allLabel}</option> : null}
        {sites.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </Select>
    </label>
  );
}
