import { useTranslation } from 'react-i18next'
import { LANGUAGES, useChangeLanguage } from '../i18n'
import { Icon } from './Icon'

/** Interface language. `up`: opens upwards (bottom of the sidebar). */
export function LanguageMenu({ signedIn = true, up = false }: { signedIn?: boolean; up?: boolean }) {
  const { t, i18n } = useTranslation()
  const change = useChangeLanguage()
  const current = i18n.resolvedLanguage
  return (
    <div className={`dropdown ${up ? 'dropdown-top' : 'dropdown-end'}`}>
      <button tabIndex={0} type="button" className="btn btn-ghost min-h-11 gap-1.5" title={t('Language')} aria-label={t('Language')}>
        <Icon name="globe" className="h-4 w-4" />
        {LANGUAGES.find((l) => l.code === current)?.short}
      </button>
      <ul tabIndex={0} className="menu dropdown-content z-40 w-40 rounded-box border border-base-300 bg-base-100 p-2 text-base-content shadow">
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
