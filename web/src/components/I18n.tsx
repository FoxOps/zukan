import { useQueryClient } from '@tanstack/react-query'
import { Fragment, useCallback, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import {
  applyLanguage,
  currentLanguage,
  I18nContext,
  LANGUAGES,
  PENDING_KEY,
  storage,
  t,
  useI18n,
  type Lang,
  type Save,
} from '../i18n'

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setState] = useState<Lang>(currentLanguage())
  const client = useQueryClient()
  const setLang = useCallback(
    (next: Lang, save: Save = 'server') => {
      if (save === 'server') {
        // Card image links depend on the user's language: reload data once saved.
        void api.PATCH('/api/auth/me', { body: { language: next } }).then(() => client.invalidateQueries())
      } else if (save === 'later') {
        storage('session')?.setItem(PENDING_KEY, next)
      }
      if (next === currentLanguage()) return
      applyLanguage(next)
      setState(next)
    },
    [client],
  )
  // Remount on change so every text is rendered again in the new language.
  return (
    <I18nContext.Provider value={{ lang, setLang }}>
      <Fragment key={lang}>{children}</Fragment>
    </I18nContext.Provider>
  )
}

export function LanguageMenu({ signedIn = true }: { signedIn?: boolean }) {
  const { lang, setLang } = useI18n()
  return (
    <div className="dropdown dropdown-end">
      <button tabIndex={0} className="btn btn-ghost btn-sm gap-1" title={t('Language')} aria-label={t('Language')}>
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2">
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
        {LANGUAGES.find((l) => l.code === lang)?.short}
      </button>
      <ul tabIndex={0} className="menu dropdown-content z-40 w-40 rounded-box bg-base-200 p-2 shadow">
        {LANGUAGES.map((l) => (
          <li key={l.code}>
            <button
              className={l.code === lang ? 'menu-active' : ''}
              lang={l.code}
              onClick={() => setLang(l.code, signedIn ? 'server' : 'later')}
            >
              {l.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
