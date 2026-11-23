import { useSyncExternalStore } from 'react'
import { readStored, store } from './storage'

/** daisyUI theme names (`web/src/index.css`); the stored choice stays "light" / "dark". */
const THEMES = { light: 'zukan', dark: 'zukan-dark' } as const
const KEY = 'tcg.theme'

export function savedDark(): boolean {
  const saved = readStored(KEY)
  return saved ? saved === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
}

export function applyTheme(dark: boolean, save = false) {
  document.documentElement.dataset.theme = THEMES[dark ? 'dark' : 'light']
  if (save) store(KEY, dark ? 'dark' : 'light')
}

// One theme for the whole page: the top bar and the settings both follow it.
let current: boolean | null = null
const listeners = new Set<() => void>()
const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
const snapshot = () => (current ??= savedDark())

/** Dark theme on or off, saved for the next visits. */
export function useTheme() {
  const dark = useSyncExternalStore(subscribe, snapshot)
  const setDark = (next: boolean) => {
    current = next
    applyTheme(next, true)
    listeners.forEach((listener) => listener())
  }
  return [dark, setDark] as const
}
