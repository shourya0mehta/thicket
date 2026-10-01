import type { ModelsResponse } from '../api/generated';

/** Model list for the static demo, where there is no server to ask. */
export const MODELS_FALLBACK: ModelsResponse = {
  models: [
    {
      key: 'birdnet',
      name: 'BirdNET',
      version: '2.4',
      description: 'Stable model for birds, with some frogs and insects.',
      taxa: ['bird', 'amphibian', 'insect'],
      experimental: false,
      status: 'ready',
      required_sample_rate_hz: 48000,
      window_seconds: 3,
      license: 'CC BY-NC-SA 4.0',
    },
  ],
};
