import type { ReactElement, ReactNode, SVGProps } from 'react';
import type { Taxon } from '../../api/types';

export type IconProps = Omit<SVGProps<SVGSVGElement>, 'children'> & { size?: number };

function Icon({
  size = 16,
  children,
  strokeWidth = 1.75,
  ...rest
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const SunIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4" />
  </Icon>
);

export const MoonIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" />
  </Icon>
);

export const InfoIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5.5" />
    <circle cx="12" cy="7.75" r="0.6" fill="currentColor" stroke="none" />
  </Icon>
);

export const CheckIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 12.5 9.5 17 19 7" />
  </Icon>
);

export const CheckCircleIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m8 12.3 2.7 2.7L16 9.5" />
  </Icon>
);

export const XIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6.5 6.5 17.5 17.5M17.5 6.5 6.5 17.5" />
  </Icon>
);

export const XCircleIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="m9 9 6 6M15 9l-6 6" />
  </Icon>
);

export const AlertIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10.3 4.2 2.9 17.5A2 2 0 0 0 4.6 20.5h14.8a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9.5v4.5" />
    <circle cx="12" cy="17" r="0.6" fill="currentColor" stroke="none" />
  </Icon>
);

export const DownloadIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 4v11M7 10.5l5 5 5-5M5 20h14" />
  </Icon>
);

export const TrashIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l1 13h9l1-13M10 11v5.5M14 11v5.5" />
  </Icon>
);

export const PlayIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={0}>
    <path
      d="M8 5.2v13.6a.8.8 0 0 0 1.2.7l10.6-6.8a.8.8 0 0 0 0-1.4L9.2 4.5A.8.8 0 0 0 8 5.2Z"
      fill="currentColor"
    />
  </Icon>
);

export const PauseIcon = (p: IconProps) => (
  <Icon {...p} strokeWidth={0}>
    <rect x="6.5" y="5" width="4" height="14" rx="1" fill="currentColor" />
    <rect x="13.5" y="5" width="4" height="14" rx="1" fill="currentColor" />
  </Icon>
);

export const RewindIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 12a8 8 0 1 0 2.4-5.7" />
    <path d="M4 4.5V9h4.5" />
  </Icon>
);

export const FileAudioIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
    <path d="M14 3v5h5" />
    <path d="M10 17.5v-5l4-1v5" />
    <circle cx="9" cy="17.5" r="1.2" />
    <circle cx="13" cy="16.5" r="1.2" />
  </Icon>
);

export const UploadIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 16V5M7 9.5l5-5 5 5M5 20h14" />
  </Icon>
);

export const MapPinIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11Z" />
    <circle cx="12" cy="10" r="2.3" />
  </Icon>
);

export const ChevronDownIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="m6 9 6 6 6-6" />
  </Icon>
);

export const SortIcon = ({
  direction,
  ...p
}: IconProps & { direction: 'asc' | 'desc' | 'none' }) => (
  <Icon {...p}>
    <path d="m8 9.5 4-4 4 4" opacity={direction === 'desc' ? 0.3 : 1} />
    <path d="m8 14.5 4 4 4-4" opacity={direction === 'asc' ? 0.3 : 1} />
  </Icon>
);

export const FlaskIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M9.5 3h5M10.5 3v6.2L5.2 18.6A1.6 1.6 0 0 0 6.6 21h10.8a1.6 1.6 0 0 0 1.4-2.4L13.5 9.2V3" />
    <path d="M7.5 15h9" />
  </Icon>
);

export const FlagIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 21V4M5 4h11.5l-2.2 4 2.2 4H5" />
  </Icon>
);

export const ShieldIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 3 19.5 6v5.5c0 4.6-3.2 8.3-7.5 9.5-4.3-1.2-7.5-4.9-7.5-9.5V6Z" />
  </Icon>
);

export const RetryIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M20 12a8 8 0 1 1-2.4-5.7" />
    <path d="M20 4.5V9h-4.5" />
  </Icon>
);

export const WaveformIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 7v10M21 12h0" />
  </Icon>
);

export const ArrowRightIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 12h14M13 6l6 6-6 6" />
  </Icon>
);

export const GridIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
    <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
    <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
  </Icon>
);

export const BellIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15Z" />
    <path d="M10 20.5a2 2 0 0 0 4 0" />
  </Icon>
);

export const MicIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="9" y="3" width="6" height="11" rx="3" />
    <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3M9 21h6" />
  </Icon>
);

export const DocumentIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
    <path d="M14 3v5h5M8.5 13h7M8.5 17h5" />
  </Icon>
);

export const UsersIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="9" cy="8" r="3" />
    <path d="M3.5 19c0-3.3 2.4-5.5 5.5-5.5s5.5 2.2 5.5 5.5" />
    <path d="M15.5 5.5a3 3 0 0 1 0 5M17.5 13.8c1.9.6 3 2.4 3 5.2" />
  </Icon>
);

export const MenuIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </Icon>
);

export const SignOutIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 8l4 4-4 4M19 12H9" />
  </Icon>
);

export const CopyIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="9" y="9" width="11" height="11" rx="2" />
    <path d="M5 15V6a2 2 0 0 1 2-2h9" />
  </Icon>
);

export const PlusIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M12 5v14M5 12h14" />
  </Icon>
);

export const ChevronRightIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="m9 6 6 6-6 6" />
  </Icon>
);

export const ChevronLeftIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="m15 6-6 6 6 6" />
  </Icon>
);

export const CalendarIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3.5" y="5" width="17" height="15" rx="2" />
    <path d="M3.5 10h17M8 3v4M16 3v4" />
  </Icon>
);

export const LeafIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M5 19c0-8 5-13 14-14-.5 9-5.5 14-14 14Z" />
    <path d="M5 19c3-4 6-7 10-10" />
  </Icon>
);

export const BatteryIcon = (p: IconProps) => (
  <Icon {...p}>
    <rect x="3" y="8" width="15" height="8" rx="2" />
    <path d="M20.5 11v2M6 11v2" />
  </Icon>
);

export const ThermometerIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a3.5 3.5 0 1 1-4 0Z" />
  </Icon>
);

export const ExternalIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M14 4h6v6M20 4l-9 9M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5" />
  </Icon>
);

/* Taxon glyphs. Always paired with a text label; never the only cue. */

export const BirdIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M4 16.5c3.4 0 5.4-1.8 6.6-4.6C11.8 9 13.6 6.5 16.8 6.5c1.9 0 3.2 1.2 3.2 2.6l2 .7-2 .7c-.4 3.9-3.4 6.5-7.8 6.5H7.5L4.5 19.5" />
    <path d="M10.6 12c1.4 1.6 3.4 2.2 5.9 1.6" />
    <circle cx="17" cy="8.8" r="0.7" fill="currentColor" stroke="none" />
  </Icon>
);

export const FrogIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="8.5" cy="7.5" r="2.2" />
    <circle cx="15.5" cy="7.5" r="2.2" />
    <path d="M6 10c-.4 4.6 2.3 8 6 8s6.4-3.4 6-8" />
    <path d="M9.5 12.5c1.5 1 3.5 1 5 0" />
    <path d="M7.2 15.5 4 18.5M16.8 15.5l3.2 3" />
  </Icon>
);

export const InsectIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="6.8" r="2" />
    <ellipse cx="12" cy="14.2" rx="3.4" ry="5.3" />
    <path d="M11 5.1 8.8 2.5M13 5.1l2.2-2.6" />
    <path d="M8.7 11.5 5.5 9.8M8.6 14.5H5M8.9 17.3 6 20M15.3 11.5l3.2-1.7M15.4 14.5H19M15.1 17.3 18 20" />
  </Icon>
);

export const PawIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="6.5" cy="10" r="1.7" />
    <circle cx="10" cy="6.3" r="1.7" />
    <circle cx="14.5" cy="6.3" r="1.7" />
    <circle cx="18" cy="10" r="1.7" />
    <path d="M8.3 16.6c0-2.9 1.9-4.8 4-4.8s4 1.9 4 4.8c0 1.8-1.4 2.6-3 2-1 .5-1.6.5-2.1 0-1.6.6-2.9-.2-2.9-2Z" />
  </Icon>
);

export const PersonIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="7.5" r="3.2" />
    <path d="M5.5 20c0-4 2.9-6.5 6.5-6.5s6.5 2.5 6.5 6.5" />
  </Icon>
);

export const CogIcon = (p: IconProps) => (
  <Icon {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M5.6 18.4l1.8-1.8M16.6 7.4l1.8-1.8" />
  </Icon>
);

export const WindIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 9h10.5a2.5 2.5 0 1 0-2.5-2.5" />
    <path d="M3 13h15a2.5 2.5 0 1 1-2.5 2.5" />
    <path d="M3 17h7" />
  </Icon>
);

export const NoiseIcon = (p: IconProps) => (
  <Icon {...p}>
    <path d="M3 12h2.5l2-5 3 10 3-12 3 14 2-7H21" />
  </Icon>
);

const TAXON_ICONS: Record<Taxon, (p: IconProps) => ReactElement> = {
  bird: BirdIcon,
  amphibian: FrogIcon,
  insect: InsectIcon,
  mammal: PawIcon,
  human: PersonIcon,
  domestic_animal: PawIcon,
  anthropogenic: CogIcon,
  environmental: WindIcon,
  noise: NoiseIcon,
};

export function TaxonIcon({ taxon, ...rest }: IconProps & { taxon: Taxon }) {
  const Component = TAXON_ICONS[taxon] ?? NoiseIcon;
  return <Component {...rest} />;
}
