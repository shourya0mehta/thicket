import type { FriendlyError } from '../../api/errors';
import { Button } from '../ui/Button';
import { Callout } from '../ui/Callout';
import { RetryIcon, UploadIcon } from '../ui/icons';

export function ErrorCallout({
  error,
  onRetry,
  onChooseFile,
  className,
}: {
  error: FriendlyError;
  onRetry?: () => void;
  onChooseFile?: () => void;
  className?: string;
}) {
  const actions = [];
  if (error.action === 'retry' && onRetry) {
    actions.push(
      <Button key="retry" size="sm" variant="primary" onClick={onRetry}>
        <RetryIcon size={14} />
        Try again
      </Button>,
    );
  }
  if (error.action === 'choose_file' && onChooseFile) {
    actions.push(
      <Button key="file" size="sm" variant="secondary" onClick={onChooseFile}>
        <UploadIcon size={14} />
        Choose another file
      </Button>,
    );
  }
  if (error.action === 'choose_model' && onRetry) {
    actions.push(
      <Button key="retry" size="sm" variant="secondary" onClick={onRetry}>
        <RetryIcon size={14} />
        Try again
      </Button>,
    );
  }

  return (
    <Callout
      tone="danger"
      role="alert"
      title={error.title}
      className={className}
      actions={actions.length ? actions : undefined}
    >
      <p data-testid="error-body" data-error-code={error.code}>
        {error.body}
      </p>
      {error.detail ? (
        <p className="mt-1 text-xs text-muted">Server message: {error.detail}</p>
      ) : null}
    </Callout>
  );
}
