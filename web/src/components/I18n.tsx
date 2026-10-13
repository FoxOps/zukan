import { useTranslation } from 'react-i18next'
import { LANGUAGES, useChangeLanguage } from '../i18n'

export function LanguageMenu({ signedIn = true }: { signedIn?: boolean }) {
  const { t, i18n } = useTranslation()
  const change = useChangeLanguage()
  const current = i18n.resolvedLanguage
  return (
    <div className="dropdown dropdown-end">
      <button tabIndex={0} className="btn btn-ghost btn-sm gap-1" title={t('Language')} aria-label={t('Language')}>
        <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2">
          <circle cx="12" cy="12" r="9" />
          <path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" />
        </svg>
        {LANGUAGES.find((l) => l.code === current)?.short}
      </button>
      <ul tabIndex={0} className="menu dropdown-content z-40 w-40 rounded-box bg-base-200 p-2 shadow">
        {LANGUAGES.map((l) => (
          <li key={l.code}>
            <button className={l.code === current ? 'menu-active' : ''} lang={l.code} onClick={() => change(l.code, signedIn)}>
              {l.label}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
