import type { ReactNode } from 'react';
import { cx } from '../../lib/cx';
import { thresholdPercent } from '../../lib/threshold';

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="grid grid-cols-[2rem_1fr] gap-x-3">
      <span
        className="num mt-0.5 flex h-7 w-7 items-center justify-center rounded-full border border-line-strong text-xs font-semibold text-accent"
        aria-hidden="true"
      >
        {n}
      </span>
      <div>
        <h4 className="text-sm font-semibold text-ink">{title}</h4>
        <div className="mt-1 space-y-2 text-sm leading-relaxed text-muted">{children}</div>
      </div>
    </li>
  );
}

function Formula({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-md bg-surface-muted px-1.5 py-0.5 font-sans text-[0.8125rem] text-ink">
      {children}
    </code>
  );
}

/**
 * Plain-language description of how results are produced. Values default to
 * BirdNET's configuration and are replaced by an analysis's recorded settings.
 */
export function MethodsExplainer({
  windowSeconds = 3,
  hopSeconds,
  rawThreshold = 0.1,
  decisionThreshold = 0.6,
  mergeGapSeconds = 1,
  className,
}: {
  windowSeconds?: number;
  hopSeconds?: number;
  rawThreshold?: number;
  decisionThreshold?: number;
  mergeGapSeconds?: number;
  className?: string;
}) {
  return (
    <ol className={cx('space-y-5', className)}>
      <Step n={1} title="Listening in windows">
        <p>
          The model scores the recording in {windowSeconds} second windows
          {hopSeconds ? `, advancing ${hopSeconds} s at a time` : ''}. Each window gets a confidence
          score for every species the model knows. Scores are model outputs, not calibrated
          probabilities.
        </p>
      </Step>
      <Step n={2} title="Two thresholds">
        <p>
          Windows below the ingestion floor ({thresholdPercent(rawThreshold)}) are not stored. The
          decision threshold (currently {thresholdPercent(decisionThreshold)}) decides which stored
          windows count. Moving the slider recomputes events, species and metrics on the server from
          the same stored windows, and the threshold used is recorded with every export.
        </p>
      </Step>
      <Step n={3} title="Windows become detection events">
        <p>
          Windows of the same species that overlap or sit within {mergeGapSeconds} s of each other
          merge into one detection event, keeping the maximum confidence and the mean over its
          windows. An event is a stretch of audio in which a species was detected. Events are not
          individuals: one bird can produce many events, and several birds can share one.
        </p>
      </Step>
      <Step n={4} title="Metrics from one event set">
        <p>
          Every metric uses the same consolidated events. With <Formula>nᵢ</Formula> events for
          species <Formula>i</Formula>, <Formula>N = Σ nᵢ</Formula> and{' '}
          <Formula>pᵢ = nᵢ / N</Formula>:
        </p>
        <ul className="list-disc space-y-1 pl-5">
          <li>
            Richness <Formula>S</Formula>: species with at least one event.
          </li>
          <li>
            Shannon <Formula>H′ = −Σ pᵢ ln pᵢ</Formula> (natural log; 0 with no events).
          </li>
          <li>
            Pielou evenness <Formula>J′ = H′ / ln S</Formula> when <Formula>S &gt; 1</Formula>,
            otherwise 0.
          </li>
          <li>
            Gini-Simpson <Formula>1 − Σ pᵢ²</Formula>.
          </li>
        </ul>
        <p>
          These describe how detection events are spread across species. They are not estimates of
          how many animals are present: loud, frequent callers produce more events, and
          detectability changes with distance, weather, microphone and season.
        </p>
      </Step>
      <Step n={5} title="What never counts">
        <p>
          Human voices, domestic animals, engines, wind, rain and noise are reported as other
          sounds, never as species. Species outside the expected range or season for the recording
          location and week are flagged and excluded, and events a reviewer rejects are removed from
          the metrics.
        </p>
      </Step>
    </ol>
  );
}
