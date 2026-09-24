import type { Taxon } from '../api/types';

/** Taxa that count toward biodiversity metrics (mirrors backend BIODIVERSITY_TAXA). */
export const BIODIVERSITY_TAXA: ReadonlySet<Taxon> = new Set<Taxon>([
  'bird',
  'amphibian',
  'insect',
  'mammal',
]);

export function isBiodiversityTaxon(taxon: Taxon): boolean {
  return BIODIVERSITY_TAXA.has(taxon);
}

export const TAXON_LABEL: Record<Taxon, string> = {
  bird: 'Bird',
  amphibian: 'Amphibian',
  insect: 'Insect',
  mammal: 'Mammal',
  human: 'Human sound',
  domestic_animal: 'Domestic animal',
  anthropogenic: 'Human-made sound',
  environmental: 'Environmental sound',
  noise: 'Noise',
};
