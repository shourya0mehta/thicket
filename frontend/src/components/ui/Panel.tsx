import type { ReactNode } from 'react';
import { cx } from '../../lib/cx';

export function Panel({
  children,
  className,
  as: Tag = 'section',
  labelledBy,
  label,
}: {
  children: ReactNode;
  className?: string;
  as?: 'section' | 'div' | 'article' | 'aside';
  labelledBy?: string;
  label?: string;
}) {
  return (
    <Tag className={cx('panel', className)} aria-labelledby={labelledBy} aria-label={label}>
      {children}
    </Tag>
  );
}
