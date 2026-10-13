import { createContext, useContext, useEffect } from 'react'
import { fr } from './fr'

/**
 * Interface translations. Texts are written in English in the code and looked up in the
 * dictionary of the chosen language (missing entries stay English). `{name}` parts are
 * replaced by the given values.
 *
 * The language is saved on the user (card images follow it) and in the browser (for the
 * login page). Provider and menu: `components/I18n.tsx`.
 */
export const LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'fr', label: 'Français', short: 'FR' },
] as const
export type Lang = (typeof LANGUAGES)[number]['code']

const DICTIONARIES: Record<Lang, Record<string, string>> = { en: {}, fr }
const STORAGE_KEY = 'tcg.ui-language'
// Set when the language is chosen before signing in, to save it on the user afterwards.
export const PENDING_KEY = 'tcg.ui-language-pending'

export function isLang(value: unknown): value is Lang {
  return LANGUAGES.some((l) => l.code === value)
}

export function storage(kind: 'local' | 'session'): Storage | null {
  try {
    return kind === 'local' ? localStorage : sessionStorage
  } catch {
    return null
  }
}

function initialLanguage(): Lang {
  const saved = storage('local')?.getItem(STORAGE_KEY)
  if (isLang(saved)) return saved
  return navigator.language?.toLowerCase().startsWith('fr') ? 'fr' : 'en'
}

let current: Lang = initialLanguage()
document.documentElement.lang = current

export function currentLanguage(): Lang {
  return current
}

/** Switch the language used by `t` (the provider re-renders the page). */
export function applyLanguage(lang: Lang) {
  current = lang
  document.documentElement.lang = lang
  storage('local')?.setItem(STORAGE_KEY, lang)
}

type Vars = Record<string, string | number>

export function t(text: string, vars?: Vars): string {
  const translated = DICTIONARIES[current][text] ?? text
  if (!vars) return translated
  return translated.replace(/\{(\w+)\}/g, (match, key: string) => (key in vars ? String(vars[key]) : match))
}

/** Singular or plural text for `count` (available as `{n}`). */
export function tn(one: string, other: string, count: number, vars?: Vars): string {
  const form = new Intl.PluralRules(current).select(count) === 'one' ? one : other
  return t(form, { n: count.toLocaleString(current), ...vars })
}

// server: save on the user; later: save once signed in; none: already saved there.
export type Save = 'server' | 'later' | 'none'
type I18n = { lang: Lang; setLang: (lang: Lang, save?: Save) => void }
export const I18nContext = createContext<I18n>({ lang: current, setLang: () => {} })

export function useI18n(): I18n {
  return useContext(I18nContext)
}

/** Once signed in, the language saved on the user wins (it may come from another
 * device), unless one was just chosen on the login page. */
export function useServerLanguage(serverLang: string | undefined) {
  const { setLang } = useI18n()
  useEffect(() => {
    if (!isLang(serverLang)) return
    const pending = storage('session')?.getItem(PENDING_KEY)
    storage('session')?.removeItem(PENDING_KEY)
    if (isLang(pending) && pending !== serverLang) setLang(pending, 'server')
    else setLang(serverLang, 'none')
  }, [serverLang, setLang])
}
