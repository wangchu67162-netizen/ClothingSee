import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#07070B',
          900: '#0B0B10',
          850: '#0E1119',
          800: '#101016',
          700: '#17171F',
          600: '#22222C',
        },
        ivory: '#F5EFE6',
        champagne: '#D8BE93',
        ember: '#FF6B3D',
        sage: '#6E8B86',
        plum: '#3A2436',
      },
      /* 仅使用本机字体栈，不加载任何在线字体 */
      fontFamily: {
        display: ['Georgia', '"Times New Roman"', '"Songti SC"', 'STSong', 'SimSun', 'serif'],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          '"Microsoft YaHei UI"',
          '"Microsoft YaHei"',
          '"PingFang SC"',
          'sans-serif',
        ],
        mono: ['"Cascadia Code"', 'Consolas', '"SFMono-Regular"', 'monospace'],
      },
      opacity: {
        2: '0.02',
        3: '0.03',
        4: '0.04',
        6: '0.06',
        8: '0.08',
        12: '0.12',
        14: '0.14',
        15: '0.15',
        18: '0.18',
        22: '0.22',
        35: '0.35',
        45: '0.45',
        55: '0.55',
        65: '0.65',
        85: '0.85',
      },
      boxShadow: {
        glass: '0 24px 80px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.14)',
        'glass-lg':
          '0 40px 120px rgba(0,0,0,.58), 0 4px 18px rgba(0,0,0,.26), inset 0 1px 0 rgba(255,255,255,.18)',
        glow: '0 0 60px rgba(216,190,147,.18)',
        'glow-soft': '0 0 34px rgba(216,190,147,.1)',
        ember: '0 0 40px rgba(255,107,61,.25)',
        ring: '0 0 0 3px rgba(216,190,147,.16)',
      },
      transitionTimingFunction: {
        expo: 'cubic-bezier(0.16, 1, 0.3, 1)',
        spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        float: {
          '0%,100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-12px)' },
        },
        shimmer: {
          '0%': { transform: 'translateX(-120%) skewX(-18deg)' },
          '100%': { transform: 'translateX(220%) skewX(-18deg)' },
        },
        breathe: {
          '0%,100%': { opacity: '.45', transform: 'scale(1)' },
          '50%': { opacity: '.8', transform: 'scale(1.06)' },
        },
        drift: {
          '0%': { transform: 'translate3d(0,0,0)' },
          '100%': { transform: 'translate3d(0,-24px,0)' },
        },
        spinSlow: {
          '0%': { transform: 'rotate(0deg)' },
          '100%': { transform: 'rotate(360deg)' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translate3d(0,14px,0)' },
          '100%': { opacity: '1', transform: 'translate3d(0,0,0)' },
        },
      },
      animation: {
        float: 'float 7s ease-in-out infinite',
        shimmer: 'shimmer 1.4s ease forwards',
        breathe: 'breathe 5s ease-in-out infinite',
        drift: 'drift 12s ease-in-out infinite alternate',
        'spin-slow': 'spinSlow 28s linear infinite',
        'fade-up': 'fadeUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) both',
      },
    },
  },
  plugins: [],
} satisfies Config
