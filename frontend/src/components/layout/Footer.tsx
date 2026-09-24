import { API_SCHEMA_VERSION } from '../../api/types';

export function Footer() {
  return (
    <footer className="mt-16 border-t border-line">
      <div className="mx-auto flex max-w-page flex-col gap-2 px-4 py-8 text-xs leading-relaxed text-muted sm:px-6 lg:flex-row lg:items-start lg:justify-between lg:gap-10 lg:px-8">
        <p className="lg:max-w-sm">
          Thicket reports acoustic detection events for review. They are evidence to check, not a
          census.
        </p>
        <p className="lg:max-w-lg lg:text-right">
          BirdNET model by the Cornell Lab of Ornithology and Chemnitz University of Technology (CC
          BY-NC-SA 4.0) · API schema {API_SCHEMA_VERSION}
        </p>
      </div>
    </footer>
  );
}
