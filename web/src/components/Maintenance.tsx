import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import type { Schemas } from '../api/client'
import { backoff } from '../api/queries'
import { Logo } from './Logo'
import { Eyebrow } from './Page'

type State = Schemas['MaintenanceOut']

/** Administrators keep access during maintenance, with this notice (users get the
 * server's maintenance page instead of the interface). */
export function MaintenanceBanner({ state }: { state: State }) {
  const { t } = useTranslation()
  const admin = state.reason === 'admin'
  return (
    <div role="alert" className="alert alert-warning alert-soft mb-6 rounded-2xl">
      <span>
        {admin
          ? t('Maintenance started by {{name}}: users see a maintenance page until an administrator stops it.', { name: state.by ?? '?' })
          : t('Maintenance: the {{game}} catalog refresh slows the server down, users see a maintenance page until the data sync is over.', { game: state.game_id })}
      </span>
      <Link to={admin ? '/admin/server' : '/admin/jobs'} className="btn btn-sm">
        {t(admin ? 'Server' : 'Data sync')}
      </Link>
    </div>
  )
}

const reload = () => window.location.reload()

/** Server back: answers its health check, without maintenance. */
async function serverBack(): Promise<boolean> {
  try {
    const response = await fetch('/api/health', { cache: 'no-store' })
    if (!response.ok) return false
    const health = (await response.json()) as { maintenance?: unknown }
    return !health.maintenance
  } catch {
    return false
  }
}

/** Shown in place of the interface when the server cannot answer (restart, update, error,
 * maintenance): the same calm page as the server's maintenance page, never error details.
 * Comes back by itself once the server answers again after being seen down (a server that
 * never stopped answering is not reloaded in a loop: "Try again" is there). */
export function MaintenanceScreen({ onBack = reload }: { onBack?: () => void }) {
  const { t } = useTranslation()
  useEffect(() => {
    let stopped = false
    let down = false
    let failures = 0
    let timer: ReturnType<typeof setTimeout>
    // One check at a time, the next one planned when it ends: 5 s, then less and less
    // often while the server stays down (30 s at most).
    const check = async () => {
      const back = await serverBack()
      if (stopped) return
      if (!back) {
        down = true
        failures += 1
      } else if (down) {
        stopped = true
        onBack()
        return
      }
      timer = setTimeout(check, backoff(5000, failures, 30_000))
    }
    timer = setTimeout(check, 5000)
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [onBack])
  return (
    <div className="flex min-h-[70vh] items-center justify-center bg-base-200 p-4">
      <div className="flex max-w-lg flex-col items-center gap-3 rounded-[20px] border border-base-300 bg-base-100 px-6 py-10 text-center">
        <Logo className="w-[180px]" />
        <Eyebrow>{t('A short break')}</Eyebrow>
        <h1 className="text-2xl">{t('Zukan is taking a break')}</h1>
        <p className="text-base-content/70">{t('Maintenance is in progress. Thank you for your patience: please come back in a few moments.')}</p>
        <button className="btn btn-primary mt-2 min-h-11" onClick={reload}>
          {t('Try again')}
        </button>
        <p className="text-xs text-base-content/70">{t('Nothing to do on your side.')}</p>
      </div>
    </div>
  )
}
