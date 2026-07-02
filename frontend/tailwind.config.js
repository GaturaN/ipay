import frappeUIPreset from 'frappe-ui/tailwind'

export default {
  presets: [frappeUIPreset],
  content: [
    './index.html',
    './src/**/*.{vue,js,ts,jsx,tsx}',
    './node_modules/frappe-ui/src/**/*.{vue,js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        ink: '#10241b',
        paper: '#f2f5f1',
        mpesa: '#007a36',
        landed: '#12b76a',
        owed: '#9a5b00',
        danger: '#c0392b',
        hairline: '#dde4dd',
      },
      fontFamily: {
        display: ['Archivo', 'ui-sans-serif', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
}
