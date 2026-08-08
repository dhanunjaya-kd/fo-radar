/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        sniper: {
          bg: '#0a0f0a',
          card: '#0f1a0f',
          border: '#1a2a1a',
          borderHover: '#2a4a2a',
          green: '#4ade80',
          greenDark: '#22c55e',
          red: '#f87171',
          yellow: '#fbbf24',
          blue: '#60a5fa',
          muted: '#4a6a4a',
          text: '#e8f5e8',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}