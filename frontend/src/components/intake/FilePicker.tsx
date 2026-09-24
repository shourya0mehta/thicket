import { useState, type DragEvent } from 'react';
import type { Preview } from '../../api/types';
import { MAX_FILE_BYTES } from '../../config';
import { cx } from '../../lib/cx';
import { fileExtension, formatBytes, formatDuration, formatHz } from '../../lib/format';
import { Button } from '../ui/Button';
import { FileAudioIcon, UploadIcon } from '../ui/icons';

export function FilePicker({
  onPick,
  file,
  fileError,
  preview,
  disabled,
  onFile,
}: {
  /** Opens the file dialog (the one hidden input lives in ControlsPanel). */
  onPick: () => void;
  file: File | null;
  fileError: string | null;
  preview: Preview | null;
  disabled?: boolean;
  onFile: (file: File | null) => void;
}) {
  const [dragging, setDragging] = useState(false);

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const dropped = event.dataTransfer.files?.[0];
    if (dropped) onFile(dropped);
  };

  const decoded = preview?.recording;

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cx(
        'flex flex-1 flex-col rounded-2xl border border-dashed p-5 transition-colors',
        file ? 'justify-start' : 'items-center justify-center text-center',
        dragging ? 'border-mark bg-mark/[0.06]' : 'border-line-strong bg-surface-muted',
      )}
      data-testid="file-dropzone"
    >
      {file ? (
        <div className="flex gap-3" data-testid="file-facts">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-mark/10 text-accent">
            <FileAudioIcon size={22} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink" title={file.name}>
              {file.name}
            </p>
            <p className="num text-xs leading-relaxed text-muted">
              {formatBytes(file.size)} · {fileExtension(file.name).replace('.', '').toUpperCase()}
              {decoded ? (
                <>
                  {' · '}
                  <span data-testid="decoded-duration">
                    {formatDuration(decoded.duration_seconds)}
                  </span>
                  {' · '}
                  {formatHz(decoded.sample_rate_hz)}
                </>
              ) : (
                <span className="block">Duration appears after decoding</span>
              )}
            </p>
          </div>
        </div>
      ) : (
        <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-mark/10 text-accent">
          <FileAudioIcon size={24} />
        </span>
      )}

      <div className={cx('flex flex-col gap-2', file ? 'mt-4 items-start' : 'items-center')}>
        <Button
          variant={file ? 'secondary' : 'primary'}
          size={file ? 'sm' : 'md'}
          onClick={onPick}
          disabled={disabled}
          aria-describedby="file-hint"
        >
          <UploadIcon size={16} />
          {file ? 'Choose another file' : 'Choose file'}
        </Button>
        <p id="file-hint" className="max-w-[16rem] text-xs text-muted">
          WAV, MP3, M4A or FLAC up to {formatBytes(MAX_FILE_BYTES)}, or drop a file here.
        </p>
      </div>

      {fileError ? (
        <p role="alert" className="mt-3 text-sm font-medium text-danger" data-testid="file-error">
          {fileError}
        </p>
      ) : null}
    </div>
  );
}
