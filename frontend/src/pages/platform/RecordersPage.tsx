import { useState, type FormEvent } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type { Recorder, RecorderCreate, RecorderMake } from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import { HealthPill } from '../../components/platform/pills';
import {
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
  SectionHeading,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { Button } from '../../components/ui/Button';
import { ArrowRightIcon, MicIcon, PlusIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { relativeTime } from '../../lib/dates';
import { MAKES, deviceName } from '../../lib/labels';
import { navigateTo, orgHref } from '../../lib/routes';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';

export function RecorderForm({
  recorder,
  onSubmit,
  onCancel,
}: {
  recorder?: Recorder | null;
  onSubmit: (body: RecorderCreate) => Promise<void>;
  onCancel?: () => void;
}) {
  const [label, setLabel] = useState(recorder?.label ?? '');
  const [make, setMake] = useState<RecorderMake>(recorder?.make ?? 'audiomoth');
  const [model, setModel] = useState(recorder?.model ?? '');
  const [serial, setSerial] = useState(recorder?.serial ?? '');
  const [firmware, setFirmware] = useState(recorder?.firmware ?? '');
  const [notes, setNotes] = useState(recorder?.notes ?? '');
  const [labelError, setLabelError] = useState<string | null>(null);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!label.trim()) {
      setLabelError('Give the recorder a label, for example "Moth 3" or the serial.');
      return;
    }
    setLabelError(null);
    setBusy(true);
    setError(null);
    try {
      await onSubmit({
        label: label.trim(),
        make,
        model: model.trim() || null,
        serial: serial.trim() || null,
        firmware: firmware.trim() || null,
        notes: notes.trim() || null,
      });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="space-y-4"
      noValidate
      data-testid="recorder-form"
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Label" required error={labelError}>
          {(props) => (
            <TextInput
              {...props}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={80}
            />
          )}
        </Field>
        <Field label="Make">
          {(props) => (
            <Select
              {...props}
              value={make}
              onChange={(e) => setMake(e.target.value as RecorderMake)}
            >
              {MAKES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Model" hint="For example AudioMoth 1.2.0 or Song Meter Mini 2.">
          {(props) => (
            <TextInput {...props} value={model} onChange={(e) => setModel(e.target.value)} />
          )}
        </Field>
        <Field label="Serial" hint="Matched against telemetry in AudioMoth comments.">
          {(props) => (
            <TextInput {...props} value={serial} onChange={(e) => setSerial(e.target.value)} />
          )}
        </Field>
        <Field label="Firmware">
          {(props) => (
            <TextInput {...props} value={firmware} onChange={(e) => setFirmware(e.target.value)} />
          )}
        </Field>
        <Field label="Notes" className="sm:col-span-2">
          {(props) => (
            <textarea
              {...props}
              className="field-input min-h-[4rem]"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
      </div>
      {error ? <ErrorCallout error={error} /> : null}
      <div className="flex gap-2">
        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? 'Saving...' : recorder ? 'Save changes' : 'Add recorder'}
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

export function RecordersPage() {
  const { api } = usePlatform();
  const { org, recorders, permissions } = useOrg();
  const [adding, setAdding] = useState(false);

  const create = async (body: RecorderCreate) => {
    const recorder = await api.createRecorder(org.id, body);
    recorders.setData((current) => [...(current ?? []), recorder]);
    setAdding(false);
    navigateTo(orgHref(org.id, 'recorder', recorder.id));
  };

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Recorders"
        description="Each device, with its health from the latest deployment: muffled microphones, level drift, gaps, clipping, battery and temperature."
        actions={
          permissions.canManage ? (
            <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
              <PlusIcon size={14} /> Add recorder
            </Button>
          ) : null
        }
      />
      {adding && permissions.canManage ? (
        <Panel className="p-5 sm:p-6" label="New recorder">
          <SectionHeading>New recorder</SectionHeading>
          <RecorderForm onSubmit={create} onCancel={() => setAdding(false)} />
        </Panel>
      ) : null}
      {recorders.error ? <ErrorState error={recorders.error} onRetry={recorders.reload} /> : null}
      {recorders.loading ? <LoadingState label="Loading recorders..." /> : null}
      {recorders.data && recorders.data.length === 0 && !adding ? (
        <EmptyState
          title="No recorders yet"
          action={
            permissions.canManage ? (
              <Button variant="primary" size="sm" onClick={() => setAdding(true)}>
                <PlusIcon size={14} /> Add your first recorder
              </Button>
            ) : null
          }
          testId="recorders-empty"
        >
          Register each device once, then record a deployment whenever it goes out to a site.
          {!permissions.canManage ? <ReadOnlyNote /> : null}
        </EmptyState>
      ) : null}
      {recorders.data?.length ? (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-testid="recorder-list">
          {recorders.data.map((r) => (
            <li key={r.id}>
              <a
                href={orgHref(org.id, 'recorder', r.id)}
                className="group flex h-full flex-col rounded-2xl border border-line-strong bg-raised p-4 transition-colors hover:border-mark/60"
                data-testid="recorder-card"
              >
                <span className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <MicIcon size={18} className="shrink-0 text-subtle" />
                    <span className="min-w-0">
                      <span className="block truncate text-base font-semibold text-ink">
                        {r.label}
                      </span>
                      <span className="block text-xs text-muted">
                        {deviceName(r.make, r.model)}
                        {r.serial ? ` · ${r.serial}` : ''}
                      </span>
                    </span>
                  </span>
                  <HealthPill status={r.health} />
                </span>
                <span className="mt-4 flex items-center justify-between text-xs text-muted">
                  <span>
                    {r.active_deployment_id ? 'Deployed' : 'Not deployed'} · last recording{' '}
                    {relativeTime(r.last_recording_at)}
                  </span>
                  <ArrowRightIcon
                    size={13}
                    className="transition-transform group-hover:translate-x-0.5"
                  />
                </span>
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
