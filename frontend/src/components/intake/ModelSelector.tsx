import type { ReactNode } from 'react';
import type { ModelInfo } from '../../api/types';
import { cx } from '../../lib/cx';
import {
  COMBINED_SELECTION,
  canOfferCombined,
  isSelectable,
  modelDisplay,
  modelStatusText,
  visibleModels,
} from '../../lib/models';
import type { ModelsState } from '../../hooks/useModels';
import { Badge } from '../ui/Badge';
import { Button } from '../ui/Button';
import { InfoTip } from '../ui/InfoTip';
import { FlaskIcon, RetryIcon } from '../ui/icons';
import { Spinner } from '../ui/Spinner';

const EXPERIMENTAL_NOTE =
  'Experimental models have not passed Thicket’s validation benchmark. Their detections are leads to check by ear, not evidence, and they may be wrong often.';

function Option({
  value,
  checked,
  disabled,
  onSelect,
  title,
  subtitle,
  description,
  status,
  experimental,
  name,
}: {
  value: string;
  checked: boolean;
  disabled: boolean;
  onSelect: (value: string) => void;
  title: string;
  subtitle: string;
  description: ReactNode;
  status: string | null;
  experimental: boolean;
  name: string;
}) {
  const id = `model-option-${value}`;
  return (
    <div className="relative">
      <label
        htmlFor={id}
        className={cx(
          'flex gap-3 rounded-xl border px-3.5 py-3 transition-colors',
          disabled
            ? 'cursor-not-allowed border-line bg-surface-muted opacity-70'
            : checked
              ? 'cursor-pointer border-mark bg-mark/[0.07] ring-1 ring-mark/40'
              : 'cursor-pointer border-line-strong bg-raised hover:border-mark/50',
        )}
      >
        <input
          id={id}
          type="radio"
          name={name}
          value={value}
          checked={checked}
          disabled={disabled}
          onChange={() => onSelect(value)}
          className="mt-1 h-4 w-4 shrink-0 accent-forest-600 dark:accent-forest-400"
          aria-describedby={`${id}-desc`}
        />
        <span className={cx('min-w-0 flex-1', experimental && 'pr-6')}>
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-sm font-semibold text-ink">{title}</span>
            {experimental ? (
              <Badge tone="info" icon={<FlaskIcon size={11} />}>
                Experimental
              </Badge>
            ) : null}
          </span>
          <span className="block text-xs font-medium text-muted">{subtitle}</span>
          <span id={`${id}-desc`} className="mt-1 block text-xs leading-relaxed text-muted">
            {status ? (
              <span className="font-medium text-warn" data-testid={`model-status-${value}`}>
                {status}
              </span>
            ) : (
              description
            )}
          </span>
        </span>
      </label>
      {experimental ? (
        <InfoTip label={`About experimental model ${title}`} className="absolute right-2.5 top-2.5">
          {EXPERIMENTAL_NOTE}
        </InfoTip>
      ) : null}
    </div>
  );
}

export function ModelSelector({
  modelsState,
  selection,
  onSelect,
  experimentalEnabled,
}: {
  modelsState: ModelsState;
  selection: string | null;
  onSelect: (value: string) => void;
  experimentalEnabled: boolean;
}) {
  const { status, models, error, reload } = modelsState;

  if (status === 'loading' || status === 'idle') {
    return (
      <p className="flex items-center gap-2 text-sm text-muted">
        <Spinner size={14} />
        Loading models...
      </p>
    );
  }

  if (status === 'error') {
    return (
      <div
        className="rounded-xl border border-danger/30 bg-danger-soft px-3.5 py-3 text-sm"
        role="alert"
      >
        <p className="font-semibold text-ink">{error?.title ?? 'Models unavailable'}</p>
        <p className="mt-0.5 text-xs text-muted">{error?.body}</p>
        <Button size="sm" className="mt-2" onClick={reload}>
          <RetryIcon size={14} />
          Try again
        </Button>
      </div>
    );
  }

  const shown = visibleModels(models, experimentalEnabled);
  if (shown.length === 0) {
    return <p className="text-sm text-muted">This server has no models available.</p>;
  }

  return (
    <div role="radiogroup" aria-label="Model" className="space-y-2">
      {shown.map((model: ModelInfo) => {
        const display = modelDisplay(model);
        return (
          <Option
            key={model.key}
            name="model"
            value={model.key}
            checked={selection === model.key}
            disabled={!isSelectable(model)}
            onSelect={onSelect}
            title={display.title}
            subtitle={display.subtitle}
            description={display.description}
            status={modelStatusText(model)}
            experimental={model.experimental}
          />
        );
      })}
      {canOfferCombined(shown, experimentalEnabled) ? (
        <Option
          name="model"
          value={COMBINED_SELECTION}
          checked={selection === COMBINED_SELECTION}
          disabled={false}
          onSelect={onSelect}
          title="Combined"
          subtitle="All ready models together"
          description="Runs every ready model on the same audio. Detections keep their model, and results are not merged across models."
          status={null}
          experimental
        />
      ) : null}
    </div>
  );
}
