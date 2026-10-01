/** Validation for scientific names typed by hand ("Genus species", optional subspecies). */
const NAME = /^[A-Z][a-z]+(?:-[a-z]+)? [a-z]+(?:-[a-z]+)?(?: [a-z]+(?:-[a-z]+)?)?$/;

export function normalizeScientificName(raw: string): string {
  const parts = raw.trim().replace(/\s+/g, ' ').split(' ');
  if (!parts.length || !parts[0]) return '';
  return [
    parts[0][0]!.toUpperCase() + parts[0].slice(1).toLowerCase(),
    ...parts.slice(1).map((p) => p.toLowerCase()),
  ].join(' ');
}

export function isScientificName(name: string): boolean {
  return NAME.test(name);
}

export interface SpeciesListParse {
  valid: string[];
  invalid: string[];
}

/** Splits a text list (newlines or commas) and keeps one entry per valid name. */
export function parseSpeciesList(text: string): SpeciesListParse {
  const valid: string[] = [];
  const invalid: string[] = [];
  const seen = new Set<string>();
  for (const line of text.split(/\r?\n|,|;/)) {
    const raw = line.trim();
    if (!raw) continue;
    const name = normalizeScientificName(raw);
    if (!isScientificName(name)) {
      invalid.push(raw);
      continue;
    }
    if (seen.has(name)) continue;
    seen.add(name);
    valid.push(name);
  }
  return { valid, invalid };
}
