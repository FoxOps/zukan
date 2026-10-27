import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import type { Schemas } from '../api/client'
import { Mascot } from './Logo'

type State = Schemas['MaintenanceOut']

/** Users while a catalog refresh slows the server down; the page comes back by itself. */
export function MaintenanceScreen() {
  const { t } = useTranslation()
  return (
    <div className="hero min-h-[60vh] bg-base-100">
      <div className="hero-content text-center">
        <div className="card max-w-md bg-base-200 shadow-sm">
          <div className="card-body items-center gap-3">
            <Mascot className="h-20 w-20 object-contain" />
            <h1 className="card-title text-2xl">{t('Maintenance in progress')}</h1>
            <p className="text-base-content/70">
              {t('The card catalog is being refreshed and the server is busy. This page comes back by itself in a few minutes.')}
            </p>
            <span className="loading loading-dots loading-md text-primary" />
          </div>
        </div>
      </div>
    </div>
  )
}

/** Administrators keep access during maintenance, with this notice. */
export function MaintenanceBanner({ state }: { state: State }) {
  const { t } = useTranslation()
  return (
    <div role="alert" className="alert alert-warning alert-soft mb-4">
      <span>
        {t('Maintenance: the {{game}} catalog refresh slows the server down, users see a maintenance page until it is fast again.', { game: state.game_id })}
      </span>
      <Link to="/admin/jobs" className="btn btn-sm">{t('Data sync')}</Link>
    </div>
  )
}
