import { cx } from '../../lib/cx';

/** Thicket mark: three leaves on one stem, a small thicket. Decorative. */
export function LeafMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={cx('shrink-0', className)}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M16 29.5c0-4.2-.1-7.9-.2-11.6"
        className="stroke-forest-700 dark:stroke-forest-300"
        strokeWidth="1.6"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M15.4 22.6C9.6 23.4 5 18.4 4 11.6c6 .1 10.4 4.4 11.4 11Z"
        className="fill-forest-400 dark:fill-forest-500"
      />
      <path
        d="M16.6 25.4c6 .9 10.5-3.9 11.4-10.4-6 .1-10.3 4-11.4 10.4Z"
        className="fill-forest-500 dark:fill-forest-400"
      />
      <path
        d="M15.9 18.4C11.5 14.6 11.7 7.4 16.4 2.8c4.5 4.3 4.2 11.6-.5 15.6Z"
        className="fill-forest-600 dark:fill-forest-300"
      />
      <path
        d="M15.9 16.9 16.3 6.5M14.6 21.6 7 13.9M17.6 24.3 25.6 17"
        className="stroke-canvas"
        strokeWidth="1.1"
        strokeLinecap="round"
        fill="none"
        opacity="0.75"
      />
    </svg>
  );
}
