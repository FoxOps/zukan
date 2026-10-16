import { useTranslation } from 'react-i18next'
import type { ViewChoice } from '../lib/views'

/** Buttons choosing how a page of results is shown (see `useView`). */
export function ViewToggle({ views, value, onChange }: { views: ViewChoice[]; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation()
  return (
    <div className="join" role="group" aria-label={t('View')}>
      {views.map((v) => (
        <button
          key={v.id}
          className={`btn join-item btn-sm ${v.id === value ? 'btn-active' : ''}`}
          aria-pressed={v.id === value}
          onClick={() => onChange(v.id)}
        >
          {v.icon}
          {t(v.label)}
        </button>
      ))}
    </div>
  )
}
