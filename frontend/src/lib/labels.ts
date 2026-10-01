/** Plain-language labels for enum values from the platform contract. */
import type {
  AlertKind,
  HabitatType,
  OrganizationKind,
  RecorderMake,
  ReportTemplateKey,
} from '../api/generated';

export const ORG_KINDS: Array<{ value: OrganizationKind; label: string }> = [
  { value: 'farm', label: 'Farm' },
  { value: 'ranch', label: 'Ranch' },
  { value: 'land_trust', label: 'Land trust' },
  { value: 'restoration_project', label: 'Restoration project' },
  { value: 'agency', label: 'Agency' },
  { value: 'research', label: 'Research' },
  { value: 'other', label: 'Other' },
];

export function orgKindLabel(kind: OrganizationKind): string {
  return ORG_KINDS.find((k) => k.value === kind)?.label ?? kind;
}

export const HABITATS: Array<{ value: HabitatType; label: string }> = [
  { value: 'pasture', label: 'Pasture' },
  { value: 'hayfield', label: 'Hayfield' },
  { value: 'cropland', label: 'Cropland' },
  { value: 'shrubland', label: 'Shrubland' },
  { value: 'forest', label: 'Forest' },
  { value: 'wetland', label: 'Wetland' },
  { value: 'riparian_buffer', label: 'Riparian buffer' },
  { value: 'pond', label: 'Pond' },
  { value: 'farmstead', label: 'Farmstead' },
  { value: 'other', label: 'Other' },
];

export function habitatLabel(value: HabitatType | null | undefined): string {
  if (!value) return 'Not set';
  return HABITATS.find((h) => h.value === value)?.label ?? value;
}

export const MAKES: Array<{ value: RecorderMake; label: string }> = [
  { value: 'audiomoth', label: 'AudioMoth' },
  { value: 'song_meter', label: 'Song Meter' },
  { value: 'phone', label: 'Phone' },
  { value: 'handheld', label: 'Handheld recorder' },
  { value: 'other', label: 'Other' },
];

export function makeLabel(make: RecorderMake): string {
  return MAKES.find((m) => m.value === make)?.label ?? make;
}

/** "AudioMoth 1.2.0" rather than "AudioMoth AudioMoth 1.2.0" when the model repeats the make. */
export function deviceName(make: RecorderMake, model: string | null | undefined): string {
  const label = makeLabel(make);
  if (!model) return label;
  return model.toLowerCase().startsWith(label.toLowerCase()) ? model : `${label} ${model}`;
}

export const TEMPLATE_LABEL: Record<ReportTemplateKey, string> = {
  evidence: 'Evidence package',
  nrcs: 'NRCS practice annex',
  aem: 'NY AEM Tier 5 annex',
  certification: 'Certification summary',
  credit: 'Biodiversity credit report',
};

export const CATEGORY_LABEL = {
  ecology: 'Ecology',
  quality: 'Audio quality',
  recorder: 'Recorder',
} as const;

export const KIND_LABEL: Record<AlertKind, string> = {
  richness_drop: 'Species richness dropped',
  activity_drop: 'Activity dropped',
  new_species_for_site: 'New species for this site',
  priority_species_detected: 'Priority species detected',
  expected_species_missing: 'Expected species not detected',
  species_surge: 'Species surge',
  low_quality_streak: 'Low audio quality streak',
  speech_detected: 'Speech detected',
  muffled_audio: 'Muffled audio',
  level_drift: 'Level drift',
  recording_gap: 'Recording gap',
  clipping_increase: 'Clipping increase',
  channel_imbalance: 'Channel imbalance',
  dc_offset: 'DC offset',
  battery_low: 'Battery low',
  temperature_extreme: 'Temperature extreme',
  clock_suspect: 'Clock suspect',
  schedule_deviation: 'Schedule deviation',
  upload_overdue: 'No new uploads',
};

export function kindLabel(kind: string): string {
  return (KIND_LABEL as Record<string, string>)[kind] ?? kind.replace(/_/g, ' ');
}
