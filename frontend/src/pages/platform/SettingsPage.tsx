import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { describeError, type FriendlyError } from '../../api/errors';
import type {
  AlertRules,
  Invite,
  Membership,
  NotificationPrefs,
  OrganizationKind,
  OrganizationUpdate,
  Role,
} from '../../api/generated';
import { ErrorCallout } from '../../components/feedback/ErrorCallout';
import {
  Checkbox,
  Field,
  LoadingState,
  PageHeader,
  ReadOnlyNote,
  SectionHeading,
  Select,
  TextInput,
} from '../../components/platform/primitives';
import { Badge } from '../../components/ui/Badge';
import { Button } from '../../components/ui/Button';
import { Callout } from '../../components/ui/Callout';
import { CopyIcon } from '../../components/ui/icons';
import { Panel } from '../../components/ui/Panel';
import { useResource } from '../../hooks/useResource';
import { formatDateTime } from '../../lib/format';
import { ROLE_HELP, ROLE_LABEL, ROLES } from '../../lib/roles';
import { inviteHref } from '../../lib/routes';
import { parseSpeciesList } from '../../lib/species';
import { isValidTimeZone, timeZoneOptions } from '../../lib/validation';
import { useOrg } from '../../platform/orgContext';
import { usePlatform } from '../../platform/platformContext';
import { ORG_KINDS } from '../../lib/labels';

function useSaver<T>(save: (value: T) => Promise<unknown>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<FriendlyError | null>(null);
  const [saved, setSaved] = useState(false);
  const run = async (value: T) => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      await save(value);
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  return { busy, error, saved, run };
}

function SavedNote({ saved }: { saved: boolean }) {
  return saved ? (
    <span className="text-xs text-ok" role="status">
      Saved
    </span>
  ) : null;
}

function OrgDetails() {
  const { api, rememberOrganization } = usePlatform();
  const { org, permissions } = useOrg();
  const [name, setName] = useState(org.name);
  const [kind, setKind] = useState<OrganizationKind>(org.kind);
  const [timezone, setTimezone] = useState(org.timezone);
  const [region, setRegion] = useState(org.region ?? '');
  const [country, setCountry] = useState(org.country ?? '');
  const [tzError, setTzError] = useState<string | null>(null);
  const saver = useSaver(async (body: OrganizationUpdate) => {
    const updated = await api.updateOrganization(org.id, body);
    rememberOrganization(updated);
  });
  const disabled = !permissions.canManage || api.readOnly;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!isValidTimeZone(timezone)) {
      setTzError('Use an IANA time zone such as America/Chicago.');
      return;
    }
    setTzError(null);
    void saver.run({
      name: name.trim() || null,
      kind,
      timezone: timezone.trim(),
      region: region.trim() || null,
      country: country.trim() || null,
    });
  };

  return (
    <Panel className="p-5 sm:p-6" labelledBy="org-details-heading">
      <SectionHeading
        id="org-details-heading"
        eyebrow="Organization"
        note={<SavedNote saved={saver.saved} />}
      >
        Details
      </SectionHeading>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
        <Field label="Name" className="sm:col-span-2">
          {(props) => (
            <TextInput
              {...props}
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={disabled}
            />
          )}
        </Field>
        <Field label="Kind">
          {(props) => (
            <Select
              {...props}
              value={kind}
              onChange={(e) => setKind(e.target.value as OrganizationKind)}
              disabled={disabled}
            >
              {ORG_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Time zone" hint="Daily rollups use this zone." error={tzError}>
          {(props) => (
            <>
              <TextInput
                {...props}
                list={`${props.id}-zones`}
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
                disabled={disabled}
                autoComplete="off"
              />
              <datalist id={`${props.id}-zones`}>
                {timeZoneOptions().map((z) => (
                  <option key={z} value={z} />
                ))}
              </datalist>
            </>
          )}
        </Field>
        <Field label="Region or state">
          {(props) => (
            <TextInput
              {...props}
              value={region}
              onChange={(e) => setRegion(e.target.value)}
              disabled={disabled}
            />
          )}
        </Field>
        <Field label="Country">
          {(props) => (
            <TextInput
              {...props}
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              disabled={disabled}
            />
          )}
        </Field>
        {saver.error ? (
          <div className="sm:col-span-2">
            <ErrorCallout error={saver.error} />
          </div>
        ) : null}
        <div className="sm:col-span-2">
          {disabled ? (
            <ReadOnlyNote />
          ) : (
            <Button type="submit" variant="primary" disabled={saver.busy}>
              {saver.busy ? 'Saving...' : 'Save details'}
            </Button>
          )}
        </div>
      </form>
    </Panel>
  );
}

function Members() {
  const { api, me } = usePlatform();
  const { org, permissions } = useOrg();
  const members = useResource((signal) => api.listMembers(org.id, signal), `members:${org.id}`);
  const invites = useResource(
    (signal) => api.listInvites(org.id, signal),
    `invites:${org.id}`,
    permissions.canManage && !api.readOnly,
  );
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('viewer');
  const [emailError, setEmailError] = useState<string | null>(null);
  const [lastInvite, setLastInvite] = useState<Invite | null>(null);
  const [copied, setCopied] = useState(false);
  const [rowError, setRowError] = useState<FriendlyError | null>(null);
  const inviter = useSaver(async (body: { email: string; role: Role }) => {
    const invite = await api.createInvite(org.id, body);
    setLastInvite(invite);
    setEmail('');
    invites.setData((current) => [invite, ...(current ?? [])]);
  });

  const changeRole = async (m: Membership, next: Role) => {
    setRowError(null);
    try {
      const updated = await api.updateMember(org.id, m.user.id, { role: next });
      members.setData((current) =>
        (current ?? []).map((x) =>
          x.user.id === m.user.id ? { ...x, ...updated, role: next } : x,
        ),
      );
    } catch (err) {
      setRowError(describeError(err));
    }
  };
  const remove = async (m: Membership) => {
    const self = m.user.id === me?.user.id;
    if (!window.confirm(self ? `Leave ${org.name}?` : `Remove ${m.user.name} from ${org.name}?`))
      return;
    setRowError(null);
    try {
      await api.removeMember(org.id, m.user.id);
      members.setData((current) => (current ?? []).filter((x) => x.user.id !== m.user.id));
      if (self) window.location.hash = '#/';
    } catch (err) {
      setRowError(describeError(err));
    }
  };

  const acceptLink = (invite: Invite): string => {
    if (invite.accept_url) return invite.accept_url;
    const token = invite.id;
    return `${window.location.origin}${window.location.pathname}${inviteHref(token)}`;
  };
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <Panel className="p-5 sm:p-6" labelledBy="members-heading">
      <SectionHeading
        id="members-heading"
        eyebrow="People"
        note={members.data ? `${members.data.length} members` : undefined}
      >
        Members and invitations
      </SectionHeading>
      {rowError ? <ErrorCallout className="mb-3" error={rowError} /> : null}
      {members.error ? <ErrorCallout error={members.error} /> : null}
      {members.loading ? <LoadingState /> : null}
      {members.data ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[32rem] text-sm" data-testid="members-table">
            <caption className="sr-only">Members of {org.name}</caption>
            <thead className="border-b border-line text-xs text-muted">
              <tr>
                <th scope="col" className="py-2 pr-3 text-left font-medium">
                  Member
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  Role
                </th>
                <th scope="col" className="px-3 py-2 text-left font-medium">
                  Joined
                </th>
                <th scope="col" className="py-2 pl-3 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {members.data.map((m) => {
                const self = m.user.id === me?.user.id;
                return (
                  <tr key={m.user.id} data-testid="member-row">
                    <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                      <span className="block font-medium text-ink">
                        {m.user.name}
                        {self ? <span className="ml-1 text-xs text-muted">(you)</span> : null}
                      </span>
                      <span className="block text-xs text-muted">{m.user.email}</span>
                    </th>
                    <td className="px-3 py-2.5">
                      {permissions.isOwner && !api.readOnly ? (
                        <Select
                          aria-label={`Role for ${m.user.name}`}
                          className="h-8 w-auto py-1"
                          value={m.role}
                          onChange={(e) => void changeRole(m, e.target.value as Role)}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {ROLE_LABEL[r]}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        <Badge tone={m.role === 'owner' ? 'accent' : 'neutral'}>
                          {ROLE_LABEL[m.role]}
                        </Badge>
                      )}
                    </td>
                    <td className="px-3 py-2.5 text-muted">{formatDateTime(m.joined_at)}</td>
                    <td className="py-2.5 pl-3 text-right">
                      {(permissions.isOwner || self) && !api.readOnly ? (
                        <Button size="sm" variant="ghost" onClick={() => void remove(m)}>
                          {self ? 'Leave' : 'Remove'}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <details className="mt-4 rounded-xl bg-surface-muted px-3 py-2 text-xs text-muted">
        <summary className="cursor-pointer font-medium text-ink">What each role can do</summary>
        <dl className="mt-2 grid gap-1 sm:grid-cols-2">
          {ROLES.map((r) => (
            <div key={r}>
              <dt className="font-medium text-ink">{ROLE_LABEL[r]}</dt>
              <dd>{ROLE_HELP[r]}</dd>
            </div>
          ))}
        </dl>
      </details>

      {permissions.canManage && !api.readOnly ? (
        <form
          className="mt-5 flex flex-wrap items-end gap-3"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            const trimmed = email.trim();
            if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmed)) {
              setEmailError('Enter an email address.');
              return;
            }
            setEmailError(null);
            void inviter.run({ email: trimmed, role });
          }}
          data-testid="invite-form"
        >
          <Field label="Invite by email" error={emailError} className="min-w-[14rem] flex-1">
            {(props) => (
              <TextInput
                {...props}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.org"
              />
            )}
          </Field>
          <Field label="Role">
            {(props) => (
              <Select {...props} value={role} onChange={(e) => setRole(e.target.value as Role)}>
                {ROLES.filter((r) => r !== 'owner' || permissions.isOwner).map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" disabled={inviter.busy}>
            {inviter.busy ? 'Sending...' : 'Send invitation'}
          </Button>
        </form>
      ) : null}
      {inviter.error ? <ErrorCallout className="mt-3" error={inviter.error} /> : null}
      {lastInvite ? (
        <Callout
          tone="ok"
          role="status"
          className="mt-3"
          title={`Invitation created for ${lastInvite.email}`}
        >
          <p className="break-all text-xs">
            Share this link if the email does not arrive: <code>{acceptLink(lastInvite)}</code>
          </p>
          <Button
            size="sm"
            variant="secondary"
            className="mt-2"
            onClick={() => void copy(acceptLink(lastInvite))}
          >
            <CopyIcon size={14} /> {copied ? 'Copied' : 'Copy link'}
          </Button>
        </Callout>
      ) : null}
      {invites.data?.length ? (
        <div className="mt-4">
          <h3 className="text-sm font-semibold text-ink">Pending invitations</h3>
          <ul className="mt-1 divide-y divide-line text-sm" data-testid="invite-list">
            {invites.data
              .filter((i) => !i.accepted_at)
              .map((i) => (
                <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span>
                    <span className="text-ink">{i.email}</span>
                    <span className="ml-2 text-xs text-muted">
                      {ROLE_LABEL[i.role]} · expires {formatDateTime(i.expires_at)}
                    </span>
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => void copy(acceptLink(i))}>
                    <CopyIcon size={14} /> Copy link
                  </Button>
                </li>
              ))}
          </ul>
        </div>
      ) : null}
    </Panel>
  );
}

const RULE_FIELDS: Array<{
  key: keyof AlertRules;
  label: string;
  help: string;
  step?: number;
  min?: number;
}> = [
  {
    key: 'min_baseline_recordings',
    label: 'Minimum comparable recordings',
    help: 'Ecology alerts stay quiet until this many recordings from the same site, hour bucket and season exist.',
    min: 1,
  },
  {
    key: 'richness_drop_mad',
    label: 'Richness drop (MADs below the median)',
    help: 'How far species richness must fall below its baseline before an alert opens. 3 is conservative.',
    step: 0.5,
  },
  {
    key: 'activity_drop_mad',
    label: 'Activity drop (MADs below the median)',
    help: 'Same rule for detection events per minute.',
    step: 0.5,
  },
  {
    key: 'species_surge_mad',
    label: 'Species surge (MADs above the median)',
    help: 'A species producing far more events than its own baseline, for example a new colony or a false-positive burst.',
    step: 0.5,
  },
  {
    key: 'expected_species_min_presence',
    label: 'Expected species: minimum presence',
    help: 'A species counts as expected when it was present in at least this share of past recordings (0 to 1).',
    step: 0.05,
    min: 0,
  },
  {
    key: 'expected_species_missing_recordings',
    label: 'Expected species: recordings without it',
    help: 'How many comparable recordings in a row may miss an expected species before an alert opens.',
    min: 1,
  },
  {
    key: 'low_quality_streak',
    label: 'Low audio quality streak',
    help: 'Consecutive recordings rated not usable before a quality alert opens.',
    min: 1,
  },
  {
    key: 'consecutive_recordings',
    label: 'Recorder checks: consecutive recordings',
    help: 'Muffled audio and similar checks need this many recordings in a row outside the baseline.',
    min: 1,
  },
  {
    key: 'gap_multiplier',
    label: 'Gap: multiple of the usual interval',
    help: 'A gap must be at least this many times the median interval between recordings.',
    step: 0.5,
    min: 1,
  },
  {
    key: 'gap_min_hours',
    label: 'Gap: minimum hours',
    help: 'And at least this long, so a single missed clip is never a gap.',
    step: 0.5,
    min: 0,
  },
  {
    key: 'temperature_min_c',
    label: 'Temperature minimum (C)',
    help: 'Below this a temperature alert opens for the recorder.',
    step: 1,
  },
  {
    key: 'temperature_max_c',
    label: 'Temperature maximum (C)',
    help: 'Above this a temperature alert opens.',
    step: 1,
  },
];

function AlertRulesForm() {
  const { api } = usePlatform();
  const { org, permissions } = useOrg();
  const rules = useResource((signal) => api.getAlertRules(org.id, signal), `rules:${org.id}`);
  const [draft, setDraft] = useState<AlertRules | null>(null);
  const [speciesText, setSpeciesText] = useState('');
  const [battery, setBattery] = useState<Record<string, string>>({});
  const disabled = !permissions.canManage || api.readOnly;
  useEffect(() => {
    if (rules.data && draft === null) {
      setDraft(rules.data);
      setSpeciesText((rules.data.priority_species ?? []).join('\n'));
      setBattery(
        Object.fromEntries(
          Object.entries(rules.data.battery_low_v ?? {}).map(([k, v]) => [k, String(v)]),
        ),
      );
    }
  }, [rules.data, draft]);
  const parsedSpecies = useMemo(() => parseSpeciesList(speciesText), [speciesText]);
  const saver = useSaver(async (body: AlertRules) => {
    const saved = await api.putAlertRules(org.id, body);
    rules.setData(saved);
    setDraft(saved);
  });

  if (rules.error) return <ErrorCallout error={rules.error} />;
  if (!draft) return <LoadingState label="Loading alert rules..." />;

  const number = (key: keyof AlertRules) => {
    const v = draft[key];
    return typeof v === 'number' ? String(v) : '';
  };
  const setNumber = (key: keyof AlertRules, raw: string) =>
    setDraft((d) => ({ ...d!, [key]: raw.trim() === '' ? undefined : Number(raw) }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const batteryMap: Record<string, number> = {};
    for (const [k, v] of Object.entries(battery)) {
      const n = Number(v);
      if (v.trim() && Number.isFinite(n)) batteryMap[k] = n;
    }
    void saver.run({
      ...draft,
      priority_species: parsedSpecies.valid,
      battery_low_v: batteryMap,
    });
  };

  return (
    <form onSubmit={submit} className="space-y-6" noValidate data-testid="alert-rules-form">
      <Panel className="p-5 sm:p-6" labelledBy="priority-heading">
        <SectionHeading id="priority-heading" eyebrow="Species of interest">
          Priority species
        </SectionHeading>
        <Field
          label="Scientific names, one per line"
          hint="Use the BirdNET label form, Genus species, for example Dolichonyx oryzivorus for Bobolink. A detection of any of these opens a priority alert and flags the species on the dashboard."
          error={
            parsedSpecies.invalid.length
              ? `Not in Genus species form: ${parsedSpecies.invalid.join(', ')}`
              : null
          }
        >
          {(props) => (
            <textarea
              {...props}
              className="field-input sci min-h-[6rem]"
              value={speciesText}
              onChange={(e) => setSpeciesText(e.target.value)}
              disabled={disabled}
              data-testid="priority-species"
            />
          )}
        </Field>
        {parsedSpecies.valid.length ? (
          <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Recognized names">
            {parsedSpecies.valid.map((name) => (
              <li key={name}>
                <Badge tone="accent">
                  <span className="sci">{name}</span>
                </Badge>
              </li>
            ))}
          </ul>
        ) : null}
      </Panel>

      <Panel className="p-5 sm:p-6" labelledBy="rules-heading">
        <SectionHeading
          id="rules-heading"
          eyebrow="Thresholds"
          note={<SavedNote saved={saver.saved} />}
        >
          Alert rules
        </SectionHeading>
        <Checkbox
          label="Alerts on"
          hint="When off, nothing new opens; existing alerts stay in the inbox."
          checked={draft.enabled ?? true}
          onChange={(e) => setDraft((d) => ({ ...d!, enabled: e.target.checked }))}
          disabled={disabled}
          className="mb-4"
        />
        <div className="grid gap-4 sm:grid-cols-2">
          {RULE_FIELDS.map((f) => (
            <Field key={f.key} label={f.label} hint={f.help}>
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  inputMode="decimal"
                  className="num"
                  step={f.step ?? 1}
                  min={f.min}
                  value={number(f.key)}
                  onChange={(e) => setNumber(f.key, e.target.value)}
                  disabled={disabled}
                  data-testid={`rule-${f.key}`}
                />
              )}
            </Field>
          ))}
        </div>
        <h3 className="mt-6 text-sm font-semibold text-ink">
          Battery low threshold by make (volts)
        </h3>
        <p className="mb-3 text-xs text-muted">
          Below this voltage a battery alert opens. AudioMoth units usually fail under 3.6 V on
          alkaline cells.
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          {['audiomoth', 'song_meter', 'other'].map((make) => (
            <Field key={make} label={make.replace(/_/g, ' ')}>
              {(props) => (
                <TextInput
                  {...props}
                  type="number"
                  inputMode="decimal"
                  className="num"
                  step={0.1}
                  value={battery[make] ?? ''}
                  onChange={(e) => setBattery((b) => ({ ...b, [make]: e.target.value }))}
                  disabled={disabled}
                />
              )}
            </Field>
          ))}
        </div>
        {saver.error ? <ErrorCallout className="mt-4" error={saver.error} /> : null}
        <div className="mt-5">
          {disabled ? (
            <ReadOnlyNote />
          ) : (
            <Button type="submit" variant="primary" disabled={saver.busy} data-testid="save-rules">
              {saver.busy ? 'Saving...' : 'Save rules and priority species'}
            </Button>
          )}
        </div>
      </Panel>
    </form>
  );
}

function NotificationPrefsForm() {
  const { api } = usePlatform();
  const prefs = useResource((signal) => api.getNotificationPrefs(signal), 'prefs');
  const [draft, setDraft] = useState<NotificationPrefs | null>(null);
  useEffect(() => {
    if (prefs.data && draft === null) setDraft(prefs.data);
  }, [prefs.data, draft]);
  const saver = useSaver(async (body: NotificationPrefs) => {
    const saved = await api.putNotificationPrefs(body);
    prefs.setData(saved);
    setDraft(saved);
  });
  if (prefs.error) return <ErrorCallout error={prefs.error} />;
  if (!draft) return <LoadingState label="Loading notification preferences..." />;
  const categories = draft.categories ?? ['ecology', 'quality', 'recorder'];
  const toggle = (c: 'ecology' | 'quality' | 'recorder', on: boolean) =>
    setDraft((d) => ({
      ...d!,
      categories: on ? [...new Set([...categories, c])] : categories.filter((x) => x !== c),
    }));

  return (
    <Panel className="p-5 sm:p-6" labelledBy="prefs-heading">
      <SectionHeading id="prefs-heading" eyebrow="You" note={<SavedNote saved={saver.saved} />}>
        Notifications
      </SectionHeading>
      <form
        className="space-y-4"
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void saver.run(draft);
        }}
        data-testid="prefs-form"
      >
        <fieldset>
          <legend className="field-label">Categories</legend>
          <div className="space-y-1.5">
            <Checkbox
              label="Ecology"
              hint="Richness, activity, new and priority species."
              checked={categories.includes('ecology')}
              onChange={(e) => toggle('ecology', e.target.checked)}
              disabled={api.readOnly}
            />
            <Checkbox
              label="Audio quality"
              hint="Low-quality streaks and speech."
              checked={categories.includes('quality')}
              onChange={(e) => toggle('quality', e.target.checked)}
              disabled={api.readOnly}
            />
            <Checkbox
              label="Recorder"
              hint="Gaps, battery, muffled audio, clock problems."
              checked={categories.includes('recorder')}
              onChange={(e) => toggle('recorder', e.target.checked)}
              disabled={api.readOnly}
            />
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Minimum severity"
            hint="Info is everything; warning is only the serious ones."
          >
            {(props) => (
              <Select
                {...props}
                value={draft.min_severity ?? 'info'}
                onChange={(e) =>
                  setDraft((d) => ({
                    ...d!,
                    min_severity: e.target.value as NotificationPrefs['min_severity'],
                  }))
                }
                disabled={api.readOnly}
              >
                <option value="info">Info and above</option>
                <option value="watch">Watch and above</option>
                <option value="warning">Warning only</option>
              </Select>
            )}
          </Field>
          <Field label="Email" hint="Email never includes audio.">
            {(props) => (
              <Select
                {...props}
                value={draft.email_enabled === false ? 'off' : (draft.email_digest ?? 'daily')}
                onChange={(e) => {
                  const v = e.target.value;
                  setDraft((d) => ({
                    ...d!,
                    email_enabled: v !== 'off',
                    email_digest: v === 'off' ? 'off' : (v as NotificationPrefs['email_digest']),
                  }));
                }}
                disabled={api.readOnly}
              >
                <option value="immediate">Immediately</option>
                <option value="daily">Daily digest</option>
                <option value="weekly">Weekly digest</option>
                <option value="off">Off (in-app only)</option>
              </Select>
            )}
          </Field>
        </div>
        {saver.error ? <ErrorCallout error={saver.error} /> : null}
        {!api.readOnly ? (
          <Button type="submit" variant="primary" disabled={saver.busy}>
            {saver.busy ? 'Saving...' : 'Save preferences'}
          </Button>
        ) : null}
      </form>
    </Panel>
  );
}

export function SettingsPage() {
  const { org } = useOrg();
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={org.name}
        title="Settings"
        description="Organization details, people and roles, the species you care about most, alert thresholds and how you want to be told."
      />
      <OrgDetails />
      <Members />
      <AlertRulesForm />
      <NotificationPrefsForm />
    </div>
  );
}
