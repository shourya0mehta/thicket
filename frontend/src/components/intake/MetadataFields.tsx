import { useId, type ReactNode } from 'react';
import { timeZoneOptions, type Metadata, type MetadataErrors } from '../../lib/validation';

function Field({
  id,
  label,
  hint,
  error,
  children,
  className,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="field-error">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="field-hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export function MetadataFields({
  metadata,
  errors,
  onChange,
  keepMetadata,
  onKeepMetadata,
  disabled,
}: {
  metadata: Metadata;
  errors: MetadataErrors;
  onChange: (patch: Partial<Metadata>) => void;
  keepMetadata: boolean;
  onKeepMetadata: (value: boolean) => void;
  disabled?: boolean;
}) {
  const base = useId();
  const ids = {
    site: `${base}-site`,
    lat: `${base}-lat`,
    lon: `${base}-lon`,
    date: `${base}-date`,
    tz: `${base}-tz`,
    zones: `${base}-zones`,
    keep: `${base}-keep`,
  };
  const describedBy = (id: string, key: keyof Metadata) =>
    errors[key] ? `${id}-error` : `${id}-hint`;
  const zones = timeZoneOptions();

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-4">
      <Field
        id={ids.site}
        label="Site name"
        hint="For example: North meadow, plot 3"
        error={errors.siteName}
        className="col-span-2"
      >
        <input
          id={ids.site}
          type="text"
          className="field-input"
          value={metadata.siteName}
          maxLength={200}
          autoComplete="off"
          disabled={disabled}
          onChange={(e) => onChange({ siteName: e.target.value })}
          aria-describedby={describedBy(ids.site, 'siteName')}
        />
      </Field>
      <Field
        id={ids.lat}
        label="Latitude"
        hint="Decimal degrees, -90 to 90"
        error={errors.latitude}
        className="col-span-2 sm:col-span-1"
      >
        <input
          id={ids.lat}
          type="text"
          inputMode="decimal"
          className="field-input num"
          placeholder="42.4412"
          value={metadata.latitude}
          disabled={disabled}
          onChange={(e) => onChange({ latitude: e.target.value })}
          aria-invalid={errors.latitude ? true : undefined}
          aria-describedby={describedBy(ids.lat, 'latitude')}
        />
      </Field>
      <Field
        id={ids.lon}
        label="Longitude"
        hint="Decimal degrees, -180 to 180"
        error={errors.longitude}
        className="col-span-2 sm:col-span-1"
      >
        <input
          id={ids.lon}
          type="text"
          inputMode="decimal"
          className="field-input num"
          placeholder="-76.4985"
          value={metadata.longitude}
          disabled={disabled}
          onChange={(e) => onChange({ longitude: e.target.value })}
          aria-invalid={errors.longitude ? true : undefined}
          aria-describedby={describedBy(ids.lon, 'longitude')}
        />
      </Field>
      <Field
        id={ids.date}
        label="Recording date and time"
        hint="Local time at the site"
        error={errors.capturedAt}
        className="col-span-2 sm:col-span-1"
      >
        <input
          id={ids.date}
          type="datetime-local"
          className="field-input num"
          value={metadata.capturedAt}
          disabled={disabled}
          onChange={(e) => onChange({ capturedAt: e.target.value })}
          aria-invalid={errors.capturedAt ? true : undefined}
          aria-describedby={describedBy(ids.date, 'capturedAt')}
        />
      </Field>
      <Field
        id={ids.tz}
        label="Time zone"
        hint="IANA name, for example America/Chicago"
        error={errors.timezone}
        className="col-span-2 sm:col-span-1"
      >
        <input
          id={ids.tz}
          type="text"
          className="field-input"
          list={zones.length ? ids.zones : undefined}
          value={metadata.timezone}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          onChange={(e) => onChange({ timezone: e.target.value })}
          aria-invalid={errors.timezone ? true : undefined}
          aria-describedby={describedBy(ids.tz, 'timezone')}
        />
        {zones.length ? (
          <datalist id={ids.zones}>
            {zones.map((zone) => (
              <option key={zone} value={zone} />
            ))}
          </datalist>
        ) : null}
      </Field>
      <div className="col-span-2 flex items-center gap-2">
        <input
          id={ids.keep}
          type="checkbox"
          checked={keepMetadata}
          onChange={(e) => onKeepMetadata(e.target.checked)}
          className="h-4 w-4 rounded accent-forest-600 dark:accent-forest-400"
        />
        <label htmlFor={ids.keep} className="text-sm text-ink">
          Keep these details for the next file
        </label>
      </div>
    </div>
  );
}
