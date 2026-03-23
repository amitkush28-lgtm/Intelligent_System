import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          900: '#0a0e17',
          800: '#0f1420',
          700: '#151c2c',
          600: '#1c2538',
          500: '#243044',
        },
        accent: {
          blue: '#3B82F6',
          green: '#10B981',
          red: '#EF4444',
          amber: '#F59E0B',
          purple: '#8B5CF6',
          indigo: '#6366F1',
          cyan: '#06B6D4',
        },
        agent: {
          geopolitical: '#8B5CF6',
          economist: '#3B82F6',
          investor: '#10B981',
          political: '#EF4444',
          sentiment: '#F59E0B',
          master: '#6366F1',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
};
export default config;
