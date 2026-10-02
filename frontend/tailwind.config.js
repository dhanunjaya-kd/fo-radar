import colors from 'tailwindcss/colors';
import plugin from 'tailwindcss/plugin';

// Oct 2 2026: the colour palette is now driven by CSS variables so the light theme is a real palette
// swap instead of a pile of per-class overrides. In DARK (the default, and the original design) every
// variable holds exactly Tailwind's stock value, so dark renders pixel-for-pixel as before. Under
// `html.light` the neutral slate scale is re-pointed to a clean white / light-grey scale and the
// bright accent shades (300/400, tuned for dark backgrounds) are re-pointed to deeper shades that keep
// contrast on white. Because it is a palette, every utility (bg-/text-/border-/ring-/from-/divide-,
// hover:, opacity suffixes like /40) follows automatically -- nothing can be missed.
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const ACCENTS = ['red', 'orange', 'amber', 'yellow', 'lime', 'green', 'emerald', 'teal', 'cyan', 'sky', 'blue', 'indigo', 'violet', 'purple', 'fuchsia', 'pink', 'rose'];
const FAMILIES = ['slate', ...ACCENTS];

const rgb = (hex) => {
  const h = hex.replace('#', '');
  return `${parseInt(h.slice(0, 2), 16)} ${parseInt(h.slice(2, 4), 16)} ${parseInt(h.slice(4, 6), 16)}`;
};

// light neutrals: near-black text steps, hairline borders, white cards on a soft grey page
const SLATE_LIGHT = {
  50: '#0f172a', 100: '#111827', 200: '#1f2937', 300: '#374151', 400: '#4b5563', 500: '#6b7280',
  600: '#9ca3af', 700: '#cfd5dc', 800: '#e3e7ec', 900: '#ffffff', 950: '#f4f5f7',
};

// accents: 300/400 are "bright on dark" text/fill shades -> deepen them for white. Pale hues need to
// go a step further than saturated ones to stay readable.
const PALE = new Set(['amber', 'yellow', 'lime', 'orange', 'cyan', 'sky']);
function accentLight(fam) {
  const c = colors[fam];
  const t400 = PALE.has(fam) ? 700 : (fam === 'teal' || fam === 'green' ? 700 : 600);
  const t300 = PALE.has(fam) ? 800 : 700;
  return {
    50: c[50], 100: c[100], 200: c[200],
    300: c[t300], 400: c[t400], 500: c[500], 600: c[600], 700: c[700],
    800: c[200], 900: c[100], 950: c[50],
  };
}

const colorVarName = (fam, s) => `--c-${fam}-${s}`;
const themedFamily = (fam) => Object.fromEntries(SHADES.map((s) => [s, `rgb(var(${colorVarName(fam, s)}) / <alpha-value>)`]));

const themeVars = plugin(({ addBase }) => {
  const dark = {}; const light = {};
  for (const fam of FAMILIES) {
    const lightScale = fam === 'slate' ? SLATE_LIGHT : accentLight(fam);
    for (const s of SHADES) {
      dark[colorVarName(fam, s)] = rgb(colors[fam][s]);
      light[colorVarName(fam, s)] = rgb(lightScale[s]);
    }
  }
  dark['--c-white'] = '255 255 255';  light['--c-white'] = '17 24 39';
  dark['--c-sniper-bg'] = '10 15 10';      light['--c-sniper-bg'] = '244 245 247';
  dark['--c-sniper-card'] = '15 26 15';    light['--c-sniper-card'] = '255 255 255';
  dark['--c-sniper-border'] = '26 42 26';  light['--c-sniper-border'] = '227 231 236';
  dark['--c-sniper-borderHover'] = '42 74 42'; light['--c-sniper-borderHover'] = '207 213 220';
  dark['--c-sniper-muted'] = '74 106 74';  light['--c-sniper-muted'] = '107 114 128';
  dark['--c-sniper-text'] = '232 245 232'; light['--c-sniper-text'] = '17 24 39';
  addBase({ ':root': dark, ':root.light, .light': light });
});

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ...Object.fromEntries(FAMILIES.map((f) => [f, themedFamily(f)])),
        white: 'rgb(var(--c-white) / <alpha-value>)',
        sniper: {
          bg: 'rgb(var(--c-sniper-bg) / <alpha-value>)',
          card: 'rgb(var(--c-sniper-card) / <alpha-value>)',
          border: 'rgb(var(--c-sniper-border) / <alpha-value>)',
          borderHover: 'rgb(var(--c-sniper-borderHover) / <alpha-value>)',
          green: '#4ade80',
          greenDark: '#22c55e',
          red: '#f87171',
          yellow: '#fbbf24',
          blue: '#60a5fa',
          muted: 'rgb(var(--c-sniper-muted) / <alpha-value>)',
          text: 'rgb(var(--c-sniper-text) / <alpha-value>)',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [themeVars],
}
