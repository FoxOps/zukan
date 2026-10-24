import { useQueryClient } from '@tanstack/react-query'
import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { useCallback, useEffect } from 'react'
import { initReactI18next } from 'react-i18next'
import { api } from '../api/client'
import de from '../locales/de.json'
import en from '../locales/en.json'
import es from '../locales/es.json'
import fr from '../locales/fr.json'

/**
 * Interface translations with i18next. Keys are the English texts (natural language
 * keys), so `locales/en.json` only holds plural forms; other languages translate every
 * key. Missing translations show the English text.
 *
 * The language is saved on the user (card images follow it) and in the browser (login
 * page, first visit: browser language).
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

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { translation: en }, fr: { translation: fr }, de: { translation: de }, es: { translation: es } },
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
})
document.documentElement.lang = i18n.resolvedLanguage ?? 'en'

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

