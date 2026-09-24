import { fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../App';

export function renderApp() {
  const user = userEvent.setup();
  const utils = render(<App />);
  return { user, ...utils };
}

export function audioFile(name = 'hollow-creek-dawn.wav', size?: number, type = 'audio/wav'): File {
  const file = new File(['RIFF0000WAVEfmt '], name, { type });
  if (size !== undefined) Object.defineProperty(file, 'size', { value: size });
  return file;
}

export function fileInput(): HTMLInputElement {
  return screen.getByTestId<HTMLInputElement>('file-input');
}

/** Simulates the browser's file dialog returning a file. */
export function chooseFile(file: File) {
  const input = fileInput();
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  fireEvent.change(input);
}

export async function runAnalysis(user: ReturnType<typeof userEvent.setup>) {
  const run = await screen.findByRole('button', { name: 'Run analysis' });
  await screen.findByRole('radio', { name: /Birds and more/ });
  await user.click(run);
  await screen.findByRole('heading', { name: 'Species with detection events' }, { timeout: 5000 });
}

export function metricValue(testId: string): string {
  const tile = screen.getByTestId(testId);
  return within(tile).getByRole('definition').textContent ?? '';
}
