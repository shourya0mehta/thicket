import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { buildStageItems, friendlyStageCopy, stageDefinitions, stageIndex } from '../../lib/stages';
import { StageList } from '../progress/StageList';
import { Spinner } from './Spinner';

describe('Spinner', () => {
  it('has a fixed, small size that cannot grow with its container', () => {
    render(
      <div style={{ width: 2000, height: 2000 }}>
        <Spinner size={16} label="Loading" />
      </div>,
    );
    const wrapper = screen.getByTestId('spinner');
    expect(wrapper).toHaveStyle({ width: '16px', height: '16px' });
    const svg = wrapper.querySelector('svg')!;
    expect(svg.getAttribute('width')).toBe('16');
    expect(svg.getAttribute('height')).toBe('16');
    expect(svg).toHaveClass('max-h-5', 'max-w-5');
    expect(wrapper).toHaveClass('shrink-0');
    expect(screen.getByRole('status')).toHaveTextContent('Loading');
  });

  it('is decorative without a label', () => {
    render(<Spinner size={12} />);
    expect(screen.queryByRole('status')).toBeNull();
    expect(screen.getByTestId('spinner').querySelector('svg')).toHaveAttribute(
      'aria-hidden',
      'true',
    );
  });
});

describe('stages', () => {
  const models = [{ key: 'birdnet', label: 'BirdNET' }];

  it('lists every pipeline stage in order, one per model', () => {
    const labels = stageDefinitions(models).map((d) => d.label);
    expect(labels).toEqual([
      'Uploading recording',
      'Waiting in queue',
      'Normalizing audio',
      'Checking audio quality',
      'Generating spectrogram',
      'Running BirdNET',
      'Consolidating detections',
      'Computing metrics',
    ]);
    const combined = stageDefinitions([...models, { key: 'perch', label: 'Perch' }]);
    expect(combined.map((d) => d.key)).toContain('model:perch');
  });

  it('maps backend stage names to positions', () => {
    const defs = stageDefinitions(models);
    expect(stageIndex(defs, 'normalizing')).toBe(2);
    expect(stageIndex(defs, 'model:birdnet')).toBe(5);
    expect(stageIndex(defs, 'model:unknown')).toBe(5);
    expect(stageIndex(defs, 'something-new')).toBe(-1);
    expect(stageIndex(defs, null)).toBe(-1);
  });

  it('renders done, active and pending states with text, not color alone', () => {
    const stages = buildStageItems({
      models,
      activeIndex: 5,
      timings: { normalizing: 180, quality: 95 },
    });
    render(<StageList stages={stages} />);
    const list = screen.getByRole('list', { name: 'Analysis stages' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(8);
    expect(items[0]).toHaveAttribute('data-state', 'done');
    expect(items[0]).toHaveTextContent('Uploading recording, done');
    expect(items[2]).toHaveTextContent('180 ms');
    expect(items[5]).toHaveAttribute('aria-current', 'step');
    expect(items[5]).toHaveTextContent('Running BirdNET, in progress');
    expect(items[7]).toHaveTextContent('Computing metrics, not started');
    // The active stage's spinner stays small.
    expect(within(items[5]!).getByTestId('spinner')).toHaveStyle({ width: '14px' });
  });

  it('marks the failing stage', () => {
    const stages = buildStageItems({ models, activeIndex: 3, failed: true });
    render(<StageList stages={stages} />);
    expect(screen.getAllByRole('listitem')[3]).toHaveTextContent('Checking audio quality, failed');
  });

  it('keeps friendly copy secondary', () => {
    expect(friendlyStageCopy('model:birdnet')).toBe('Crunching the birdsongs...');
    expect(friendlyStageCopy('uploading')).toMatch(/Sending/);
  });
});
