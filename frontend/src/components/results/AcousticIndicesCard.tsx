import type { AcousticIndices } from '../../api/types';
import { formatNumber } from '../../lib/format';
import { Panel } from '../ui/Panel';

const INDICES: Array<{
  key: keyof AcousticIndices;
  abbr: string;
  name: string;
  about: string;
  digits: number;
}> = [
  {
    key: 'acoustic_complexity_index',
    abbr: 'ACI',
    name: 'Acoustic Complexity',
    about:
      'How much intensity fluctuates over time within frequency bands. Birdsong tends to raise it; steady hum does not.',
    digits: 1,
  },
  {
    key: 'acoustic_diversity_index',
    abbr: 'ADI',
    name: 'Acoustic Diversity',
    about:
      'Shannon diversity of sound energy across frequency bands. Higher when many bands are active.',
    digits: 2,
  },
  {
    key: 'acoustic_evenness_index',
    abbr: 'AEI',
    name: 'Acoustic Evenness',
    about:
      'Gini inequality of energy across frequency bands. Lower means energy is spread more evenly.',
    digits: 2,
  },
  {
    key: 'bioacoustic_index',
    abbr: 'BI',
    name: 'Bioacoustic',
    about:
      'Sound energy in the 2 to 8 kHz band, where many birds and insects call, above the quietest level.',
    digits: 1,
  },
  {
    key: 'ndsi',
    abbr: 'NDSI',
    name: 'Soundscape Difference',
    about:
      'Biophony (2 to 8 kHz) against anthrophony (1 to 2 kHz), from -1 (mostly human-made sound) to 1 (mostly biological sound).',
    digits: 2,
  },
  {
    key: 'spectral_entropy',
    abbr: 'Hf',
    name: 'Spectral entropy',
    about:
      'How evenly energy is spread across frequencies, from 0 (a pure tone) to 1 (flat noise).',
    digits: 2,
  },
  {
    key: 'temporal_entropy',
    abbr: 'Ht',
    name: 'Temporal entropy',
    about: 'How evenly energy is spread over time, from 0 (one burst) to 1 (constant).',
    digits: 2,
  },
];

export function AcousticIndicesCard({ indices }: { indices: AcousticIndices | null | undefined }) {
  return (
    <Panel labelledBy="indices-heading" className="p-5 sm:p-6">
      <p className="eyebrow mb-1">Soundscape</p>
      <h3 id="indices-heading" className="text-base font-semibold tracking-tight text-ink">
        Acoustic indices
      </h3>
      <p className="mt-1 text-sm text-muted">
        Signal-level soundscape indices, independent of species detection. They summarize the
        recording&apos;s energy and do not change with the decision threshold.
      </p>
      {indices ? (
        <ul className="mt-4 grid gap-x-6 sm:grid-cols-2" data-testid="acoustic-indices">
          {INDICES.map((index) => (
            <li key={index.key} className="flex items-start gap-4 border-t border-line py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink">
                  {index.name}{' '}
                  <abbr title={index.name} className="text-xs font-normal text-muted no-underline">
                    {index.abbr}
                  </abbr>
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-muted">{index.about}</p>
              </div>
              <p className="num shrink-0 pt-0.5 text-base font-semibold text-ink">
                {formatNumber(indices[index.key], index.digits)}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-sm text-muted">
          Acoustic indices were not computed for this analysis.
        </p>
      )}
    </Panel>
  );
}
