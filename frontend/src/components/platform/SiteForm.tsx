import { useState, type FormEvent } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { HabitatType, Site, SiteCreate } from '../../api/generated';
import { HABITATS } from '../../lib/labels';
import { draftFrom, siteBodyFrom, validateSiteDraft, type SiteDraft } from '../../lib/siteForm';
import { ErrorCallout } from '../feedback/ErrorCallout';
import { Button } from '../ui/Button';
import { Field, Select, TextInput } from './primitives';

export function SiteForm({
  site,
  onSubmit,
  onCancel,
  submitLabel,
}: {
  site?: Site | null;
  onSubmit: (body: SiteCreate) => Promise<void>;
  onCancel?: () => void;
  submitLabel?: string;
}) {
  const [draft, setDraft] = useState<SiteDraft>(() => draftFrom(site));
  const [errors, setErrors] = useState<Partial<Record<keyof SiteDraft, string>>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const set = (patch: Partial<SiteDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const next = validateSiteDraft(draft);
    setErrors(next);
    if (Object.keys(next).length) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(siteBodyFrom(draft));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate data-testid="site-form">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Site name" required error={errors.name} className="sm:col-span-2">
          {(props) => (
            <TextInput
              {...props}
              value={draft.name}
              onChange={(e) => set({ name: e.target.value })}
              placeholder="North pasture"
              maxLength={200}
            />
          )}
        </Field>
        <Field label="Habitat">
          {(props) => (
            <Select
              {...props}
              value={draft.habitat}
              onChange={(e) => set({ habitat: e.target.value as HabitatType | '' })}
            >
              <option value="">Not set</option>
              {HABITATS.map((h) => (
                <option key={h.value} value={h.value}>
                  {h.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Area" hint="Hectares, optional." error={errors.area}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              className="num"
              value={draft.area}
              onChange={(e) => set({ area: e.target.value })}
            />
          )}
        </Field>
        <Field label="Latitude" hint="Decimal degrees, -90 to 90" error={errors.latitude}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              className="num"
              placeholder="42.4412"
              value={draft.latitude}
              onChange={(e) => set({ latitude: e.target.value })}
            />
          )}
        </Field>
        <Field label="Longitude" hint="Decimal degrees, -180 to 180" error={errors.longitude}>
          {(props) => (
            <TextInput
              {...props}
              inputMode="decimal"
              className="num"
              placeholder="-76.4985"
              value={draft.longitude}
              onChange={(e) => set({ longitude: e.target.value })}
            />
          )}
        </Field>
        <Field label="FSA field number" hint="For NRCS paperwork, optional.">
          {(props) => (
            <TextInput
              {...props}
              value={draft.fsa}
              onChange={(e) => set({ fsa: e.target.value })}
            />
          )}
        </Field>
        <Field label="Paddock or pasture ID" hint="Optional.">
          {(props) => (
            <TextInput
              {...props}
              value={draft.paddock}
              onChange={(e) => set({ paddock: e.target.value })}
            />
          )}
        </Field>
        <Field label="Notes" className="sm:col-span-2">
          {(props) => (
            <textarea
              {...props}
              className="field-input min-h-[5rem]"
              value={draft.notes}
              onChange={(e) => set({ notes: e.target.value })}
            />
          )}
        </Field>
      </div>
      {error ? <ErrorCallout error={error} /> : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving...' : (submitLabel ?? (site ? 'Save changes' : 'Add site'))}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
      </div>
    </form>
  );
}
