import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{vue,ts}'],
  theme: {
    extend: {
      colors: {
        canvas: '#f6f7f7',
        surface: '#ffffff',
        ink: '#18211f',
        muted: '#5f6b67',
        line: '#d8dddb',
        accent: '#0f766e',
        'accent-soft': '#ccfbf1',
        success: '#15803d',
        warning: '#b45309',
        danger: '#b91c1c',
      },
      boxShadow: {
        focus: '0 0 0 3px rgba(15, 118, 110, 0.22)',
      },
    },
  },
  plugins: [],
} satisfies Config
