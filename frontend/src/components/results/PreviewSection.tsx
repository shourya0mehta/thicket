import { resolveApiUrl } from '../../api/client';
import { sanitizeCopy } from '../../lib/models';
import type { Preview } from '../../api/types';
import { QualityBadge } from './QualityPanel';
import { RecordingCard } from './RecordingCard';

/** Spectrogram and file facts before any model runs. */
export function PreviewSection({ preview }: { preview: Preview }) {
  const q = preview.quality;
  const notes = [
    ...q.checks.filter((c) => c.status !== 'pass').map((c) => c.message),
    ...q.warnings,
  ].map(sanitizeCopy);
  return (
    <section aria-label="Recording preview" className="animate-fade-in-up">
      <div className="grid gap-5 lg:grid-cols-12">
        <div className="min-w-0 lg:col-span-8">
          <RecordingCard
            recording={preview.recording}
            spectrogramUrl={resolveApiUrl(preview.spectrogram_url)}
            minHz={preview.spectrogram_min_hz ?? 0}
            maxHz={preview.spectrogram_max_hz ?? 16000}
            headingId="preview-heading"
            eyebrow="Preview"
            headerExtra={<QualityBadge status={q.status} />}
          />
        </div>
        <aside className="min-w-0 lg:col-span-4" aria-labelledby="preview-quality-heading">
          <div className="panel p-5 sm:p-6">
            <p className="eyebrow mb-1">Before you run</p>
            <h3
              id="preview-quality-heading"
              className="text-base font-semibold tracking-tight text-ink"
            >
              Audio check
            </h3>
            <p className="mt-2 text-sm text-muted">
              Usability score{' '}
              <span className="num font-semibold text-ink">{Math.round(q.score * 100)} / 100</span>.
              {q.status === 'not_usable'
                ? ' The analysis can still run, but results are likely to be unreliable.'
                : ' Listen to a few seconds and check the spectrogram for wind or handling noise.'}
            </p>
            {notes.length ? (
              <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink">
                {notes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-ink">No problems found.</p>
            )}
            {q.speech_detected ? (
              <p className="mt-3 text-xs text-muted">
                Speech may be present. Audio is not kept after the analysis finishes.
              </p>
            ) : null}
          </div>
        </aside>
      </div>
    </section>
  );
}
