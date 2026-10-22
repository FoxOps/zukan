/** daisyUI theme names (`web/src/index.css`); the stored choice stays "light" / "dark". */
const THEMES = { light: 'zukan', dark: 'zukan-dark' } as const
const KEY = 'tcg.theme'

export function savedDark(): boolean {
  const saved = localStorage.getItem(KEY)
  return saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(dark: boolean, save = false) {
  document.documentElement.dataset.theme = THEMES[dark ? 'dark' : 'light']
  if (save) localStorage.setItem(KEY, dark ? 'dark' : 'light')
}
