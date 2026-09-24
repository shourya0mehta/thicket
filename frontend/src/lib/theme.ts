import { THEME_KEY } from '../config';
import { readStorage, writeStorage } from './storage';

export type Theme = 'light' | 'dark';

export function readStoredTheme(): Theme | null {
  const value = readStorage(THEME_KEY);
  return value === 'light' || value === 'dark' ? value : null;
}

export function storeTheme(theme: Theme): void {
  writeStorage(THEME_KEY, theme);
}

export function systemTheme(): Theme {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function initialTheme(): Theme {
  return readStoredTheme() ?? systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle('dark', theme === 'dark');
}
