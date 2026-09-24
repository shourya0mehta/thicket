import type { Config } from 'tailwindcss';
import defaultTheme from 'tailwindcss/defaultTheme';

/** Semantic colors resolve to CSS variables defined per theme in src/index.css. */
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        forest: {
          50: '#f1f6f3',
          100: '#dfebe4',
          200: '#bfd6c9',
          300: '#95baa6',
          400: '#689a80',
          500: '#4a8065',
          600: '#377157',
          700: '#2f5c47',
          800: '#224235',
          900: '#19322a',
          950: '#0d1d17',
        },
        canvas: token('canvas'),
        ink: token('ink'),
        muted: token('muted'),
        subtle: token('subtle'),
        accent: token('accent'),
        raised: token('raised'),
        viz: {
          DEFAULT: '#0b1310',
          ink: '#c9d5ce',
          muted: '#9fb0a7',
          line: '#2a3a33',
        },
        mark: token('mark'),
        warn: { DEFAULT: token('warn'), soft: token('warn-soft') },
        danger: { DEFAULT: token('danger'), soft: token('danger-soft') },
        ok: { DEFAULT: token('ok'), soft: token('ok-soft') },
        info: { DEFAULT: token('info'), soft: token('info-soft') },
      },
      borderColor: {
        line: 'rgb(var(--line))',
        'line-strong': 'rgb(var(--line-strong))',
      },
      divideColor: {
        line: 'rgb(var(--line))',
      },
      backgroundColor: {
        surface: 'rgb(var(--surface))',
        'surface-muted': 'rgb(var(--surface-muted))',
      },
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', ...defaultTheme.fontFamily.sans],
      },
      borderRadius: {
        '2xl': '1.25rem',
      },
      boxShadow: {
        soft: '0 1px 2px rgb(16 28 22 / 0.04), 0 6px 20px -8px rgb(16 28 22 / 0.08)',
        lift: '0 2px 4px rgb(16 28 22 / 0.05), 0 12px 32px -12px rgb(16 28 22 / 0.18)',
      },
      maxWidth: {
        page: '80rem',
      },
      keyframes: {
        'fade-in-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
      animation: {
        'fade-in-up': 'fade-in-up 280ms cubic-bezier(0.2, 0.7, 0.2, 1) both',
        'fade-in': 'fade-in 200ms ease-out both',
      },
    },
  },
  plugins: [],
} satisfies Config;
