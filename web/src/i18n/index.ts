import { useQueryClient } from '@tanstack/react-query'
import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { useCallback, useEffect } from 'react'
import { initReactI18next } from 'react-i18next'
import { api } from '../api/client'
import en from '../locales/en.json'

/**
 * Interface translations with i18next. Keys are the English texts (natural language
 * keys), so `locales/en.json` only holds plural forms; other languages translate every
 * key. Missing translations show the English text.
 *
 * The language is saved on the user (card images follow it) and in the browser (login
 * page, first visit: browser language). English is bundled; other languages are
 * downloaded when chosen (only one is ever needed).
 */
export const LANGUAGES = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'fr', label: 'Français', short: 'FR' },
  { code: 'de', label: 'Deutsch', short: 'DE' },
  { code: 'es', label: 'Español', short: 'ES' },
] as const
export type Lang = (typeof LANGUAGES)[number]['code']

// Set when the language is chosen before signing in, to save it on the user afterwards.
const PENDING_KEY = 'tcg.ui-language-pending'

const LOADERS: Record<string, () => Promise<{ default: Record<string, string> }>> = {
  fr: () => import('../locales/fr.json'),
  de: () => import('../locales/de.json'),
  es: () => import('../locales/es.json'),
}

/** Download the translations of `lang` once; components re-render when they arrive. */
async function loadLanguage(lang: string | undefined) {
  const loader = lang ? LOADERS[lang] : undefined
  if (!lang || !loader || i18n.hasResourceBundle(lang, 'translation')) return
  try {
    i18n.addResourceBundle(lang, 'translation', (await loader()).default)
  } catch {
    // Offline, or a new release replaced the file: English stays shown.
  }
}

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en } },
    partialBundledLanguages: true,
    // Re-render when a language's translations are added.
    react: { bindI18nStore: 'added' },
    fallbackLng: 'en',
    supportedLngs: LANGUAGES.map((l) => l.code),
    nonExplicitSupportedLngs: true,
    load: 'languageOnly',
    // Natural language keys contain dots and colons.
    keySeparator: false,
    nsSeparator: false,
    // React escapes values already.
    interpolation: { escapeValue: false },
    detection: {
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: 'tcg.ui-language',
      caches: ['localStorage'],
    },
  })

i18n.on('languageChanged', (lang) => {
  document.documentElement.lang = lang
  void loadLanguage(i18n.resolvedLanguage)
})
document.documentElement.lang = i18n.resolvedLanguage ?? 'en'
void loadLanguage(i18n.resolvedLanguage)

export default i18n

export function isLang(value: unknown): value is Lang {
  return LANGUAGES.some((l) => l.code === value)
}

/** The interface language, for Intl formatting outside React components. */
export function currentLanguage(): Lang {
  const lang = i18n.resolvedLanguage
  return isLang(lang) ? lang : 'en'
}

function session(): Storage | null {
  try {
    return sessionStorage
  } catch {
    return null
  }
}

/** Change the interface language. Signed in, it is saved on the user and data is
 * reloaded (card image links depend on it); otherwise it is saved after signing in. */
export function useChangeLanguage() {
  const client = useQueryClient()
  return useCallback(
    (lang: Lang, signedIn = true) => {
      void i18n.changeLanguage(lang)
      if (signedIn) {
        void api.PATCH('/api/auth/me', { body: { language: lang } }).then(() => client.invalidateQueries())
      } else {
        session()?.setItem(PENDING_KEY, lang)
      }
    },
    [client],
  )
}

/** Once signed in, the language saved on the user wins (it may come from another
 * device), unless one was just chosen on the login page. */
export function useServerLanguage(serverLang: string | undefined) {
  const change = useChangeLanguage()
  useEffect(() => {
    if (!isLang(serverLang)) return
    const pending = session()?.getItem(PENDING_KEY)
    session()?.removeItem(PENDING_KEY)
    if (isLang(pending) && pending !== serverLang) change(pending)
    else if (serverLang !== currentLanguage()) void i18n.changeLanguage(serverLang)
  }, [serverLang, change])
}

