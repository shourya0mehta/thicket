import { InfoIcon } from '../ui/icons';

export function DemoBanner() {
  return (
    <div className="border-b border-info/20 bg-info-soft" role="note" data-testid="demo-banner">
      <p className="mx-auto flex max-w-page items-start gap-2 px-4 py-2.5 text-sm text-ink sm:px-6 lg:px-8">
        <InfoIcon size={16} className="mt-0.5 shrink-0 text-info" />
        <span>
          <span className="font-semibold">Demo:</span> precomputed analyses of openly licensed
          recordings. Run Thicket locally to analyze your own audio.
        </span>
      </p>
    </div>
  );
}
