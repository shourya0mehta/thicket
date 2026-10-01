import type { HabitatType, Site, SiteCreate } from '../api/generated';

export interface SiteDraft {
  name: string;
  habitat: HabitatType | '';
  latitude: string;
  longitude: string;
  area: string;
  fsa: string;
  paddock: string;
  notes: string;
}

export function draftFrom(site?: Site | null): SiteDraft {
  return {
    name: site?.name ?? '',
    habitat: site?.habitat_type ?? '',
    latitude: site?.latitude != null ? String(site.latitude) : '',
    longitude: site?.longitude != null ? String(site.longitude) : '',
    area: site?.area_hectares != null ? String(site.area_hectares) : '',
    fsa: site?.fsa_field_number ?? '',
    paddock: site?.paddock_id ?? '',
    notes: site?.notes ?? '',
  };
}

function parseNumber(raw: string): number | null {
  const text = raw.trim();
  if (!text) return null;
  if (!/^[-+]?\d+(\.\d+)?$/.test(text)) return Number.NaN;
  return Number(text);
}

export function validateSiteDraft(d: SiteDraft): Partial<Record<keyof SiteDraft, string>> {
  const errors: Partial<Record<keyof SiteDraft, string>> = {};
  if (!d.name.trim()) errors.name = 'Give the site a name people will recognize.';
  const lat = parseNumber(d.latitude);
  const lon = parseNumber(d.longitude);
  if (lat !== null && (Number.isNaN(lat) || lat < -90 || lat > 90)) {
    errors.latitude = 'Latitude must be a number between -90 and 90.';
  }
  if (lon !== null && (Number.isNaN(lon) || lon < -180 || lon > 180)) {
    errors.longitude = 'Longitude must be a number between -180 and 180.';
  }
  if (lat !== null && lon === null && !errors.latitude) {
    errors.longitude = 'Add a longitude too, or clear the latitude.';
  }
  if (lon !== null && lat === null && !errors.longitude) {
    errors.latitude = 'Add a latitude too, or clear the longitude.';
  }
  const area = parseNumber(d.area);
  if (area !== null && (Number.isNaN(area) || area < 0)) {
    errors.area = 'Area must be a positive number of hectares.';
  }
  return errors;
}

export function siteBodyFrom(d: SiteDraft): SiteCreate {
  const lat = parseNumber(d.latitude);
  const lon = parseNumber(d.longitude);
  const area = parseNumber(d.area);
  return {
    name: d.name.trim(),
    habitat_type: d.habitat || null,
    latitude: lat === null || Number.isNaN(lat) ? null : lat,
    longitude: lon === null || Number.isNaN(lon) ? null : lon,
    area_hectares: area === null || Number.isNaN(area) ? null : area,
    fsa_field_number: d.fsa.trim() || null,
    paddock_id: d.paddock.trim() || null,
    notes: d.notes.trim() || null,
  };
}
