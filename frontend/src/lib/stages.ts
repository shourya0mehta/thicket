export type StageState = 'done' | 'active' | 'pending' | 'failed';

export interface StageItem {
  key: string;
  label: string;
  state: StageState;
  durationMs: number | null;
}

export interface StageModel {
  key: string;
  label: string;
}

const BEFORE_MODELS: Array<{ key: string; label: string }> = [
  { key: 'uploading', label: 'Uploading recording' },
  { key: 'queued', label: 'Waiting in queue' },
  { key: 'normalizing', label: 'Normalizing audio' },
  { key: 'quality', label: 'Checking audio quality' },
  { key: 'spectrogram', label: 'Generating spectrogram' },
];

const AFTER_MODELS: Array<{ key: string; label: string }> = [
  { key: 'consolidating', label: 'Consolidating detections' },
  { key: 'metrics', label: 'Computing metrics' },
];

export function stageDefinitions(models: StageModel[]): Array<{ key: string; label: string }> {
  const modelStages = (models.length ? models : [{ key: 'model', label: 'the model' }]).map(
    (m) => ({ key: `model:${m.key}`, label: `Running ${m.label}` }),
  );
  return [...BEFORE_MODELS, ...modelStages, ...AFTER_MODELS];
}

/** Index of a backend stage in the list, or -1 when the stage is unknown. */
export function stageIndex(defs: Array<{ key: string }>, stage: string | null | undefined): number {
  if (!stage) return -1;
  const exact = defs.findIndex((d) => d.key === stage);
  if (exact >= 0) return exact;
  if (stage.startsWith('model:') || stage === 'model') {
    return defs.findIndex((d) => d.key.startsWith('model:'));
  }
  return -1;
}

export interface StageInput {
  models: StageModel[];
  /** Index of the stage currently running; defs.length when everything finished. */
  activeIndex: number;
  failed?: boolean;
  timings?: Record<string, number> | null;
}

export function buildStageItems({
  models,
  activeIndex,
  failed = false,
  timings,
}: StageInput): StageItem[] {
  const defs = stageDefinitions(models);
  return defs.map((def, index) => {
    let state: StageState = 'pending';
    if (index < activeIndex) state = 'done';
    else if (index === activeIndex) state = failed ? 'failed' : 'active';
    const timing = timings?.[def.key];
    return {
      key: def.key,
      label: def.label,
      state,
      durationMs: state === 'done' && typeof timing === 'number' ? timing : null,
    };
  });
}

/** Secondary, friendly copy for the running stage. Never replaces the stage list. */
export function friendlyStageCopy(stageKey: string | null | undefined): string {
  if (!stageKey) return 'Getting ready...';
  if (stageKey === 'uploading') return 'Sending the recording to your Thicket server...';
  if (stageKey === 'queued') return 'Waiting for the analysis worker...';
  if (stageKey.startsWith('model:')) return 'Crunching the birdsongs...';
  if (stageKey === 'consolidating') return 'Merging adjacent windows into detection events...';
  if (stageKey === 'metrics') return 'Tallying detection events per species...';
  return 'Preparing the audio...';
}
