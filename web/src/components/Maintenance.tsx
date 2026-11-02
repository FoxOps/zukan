import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import type { Schemas } from '../api/client'

type State = Schemas['MaintenanceOut']

/** Administrators keep access during maintenance, with this notice (users get the
 * server's maintenance page instead of the interface). */
export function MaintenanceBanner({ state }: { state: State }) {
  const { t } = useTranslation()
  return (
    <div role="alert" className="alert alert-warning alert-soft mb-4">
      <span>
        {t('Maintenance: the {{game}} catalog refresh slows the server down, users see a maintenance page until the data sync is over.', { game: state.game_id })}
      </span>
      <Link to="/admin/jobs" className="btn btn-sm">{t('Data sync')}</Link>
    </div>
  )
}
