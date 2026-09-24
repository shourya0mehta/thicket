import { cx } from '../../lib/cx';

export type SpinnerSize = 12 | 14 | 16 | 20;

/**
 * A small activity indicator. The size is fixed through SVG attributes and a
 * max-size class so it can never grow to fill its container, even unstyled.
 */
export function Spinner({
  size = 16,
  label,
  className,
}: {
  size?: SpinnerSize;
  label?: string;
  className?: string;
}) {
  return (
    <span
      className={cx('inline-flex shrink-0 items-center justify-center', className)}
      style={{ width: size, height: size }}
      role={label ? 'status' : undefined}
      data-testid="spinner"
    >
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        focusable="false"
        className="max-h-5 max-w-5 motion-safe:animate-spin"
      >
        <circle
          cx="12"
          cy="12"
          r="9"
          stroke="currentColor"
          strokeOpacity="0.22"
          strokeWidth="2.5"
        />
        <path
          d="M21 12a9 9 0 0 0-9-9"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      {label ? <span className="sr-only">{label}</span> : null}
    </span>
  );
}
