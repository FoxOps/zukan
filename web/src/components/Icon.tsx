// Line icons of the Field Journal design (24px grid, 2px stroke, current color).
const PATHS = {
  home: 'M3 11 12 3l9 8v10h-6v-7H9v7H3Z',
  collection: 'M4 5h13v16H4ZM8 2h13v15',
  search: 'M21 21l-5-5M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  binder: 'M3 3h7a3 3 0 0 1 3 3v16a3 3 0 0 0-3-3H3ZM13 6a3 3 0 0 1 3-3h6v16h-6a3 3 0 0 0-3 3',
  decks: 'm12 2 10 5-10 5L2 7Zm-10 10 10 5 10-5M2 17l10 5 10-5',
  chart: 'M3 3v18h18M6 15l5-5 4 3 6-8',
  download: 'M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4',
  settings: 'M9 3h6l1 4 4 1v7l-4 1-1 5H9l-1-5-5-1V8l5-1ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  users: 'M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0M4 22v-3a8 8 0 0 1 16 0v3',
  groups: 'M9 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0M21 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0M1 21v-2a5 5 0 0 1 10 0v2M13 21v-2a5 5 0 0 1 10 0v2',
  sync: 'M20 12a8 8 0 0 1-14 5.3M4 12a8 8 0 0 1 14-5.3M18 3v4h-4M6 21v-4h4',
  checks: 'm4 12 5 5L20 6M4 20h16',
  server: 'M4 4h16v6H4ZM4 14h16v6H4ZM8 7h.01M8 17h.01',
  plus: 'M12 4v16M4 12h16',
  minus: 'M4 12h16',
  arrow: 'M4 12h16m-6-6 6 6-6 6',
  chevron: 'm9 5 7 7-7 7',
  menu: 'M3 6h18M3 12h18M3 18h18',
  moon: 'M20 15A8 8 0 0 1 9 4a8 8 0 1 0 11 11',
  sun: 'M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z',
  filter: 'M3 5h18M6 12h12M9 19h6',
  check: 'm4 12 5 5L20 6',
  grid: 'M3 3h7v7H3Zm11 0h7v7h-7ZM3 14h7v7H3Zm11 0h7v7h-7Z',
  list: 'M8 5h13M8 12h13M8 19h13M3 5h.01M3 12h.01M3 19h.01',
  close: 'm5 5 14 14M19 5 5 19',
  card: 'M6 2h12a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2ZM7 6h10v7H7Zm0 11h7',
  globe: 'M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0M3 12h18M12 3c5 5 5 13 0 18-5-5-5-13 0-18',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20ZM12 16v-5M12 8h.01',
} as const

export type IconName = keyof typeof PATHS

export function Icon({ name, className = 'h-5 w-5' }: { name: IconName; className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      aria-hidden="true"
      className={`shrink-0 fill-none stroke-current stroke-2 [stroke-linecap:round] [stroke-linejoin:round] ${className}`}
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
