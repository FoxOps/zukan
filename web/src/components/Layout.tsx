import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { api, ApiError, onSessionExpired } from '../api/client'
import { useHealth, useMe } from '../api/queries'
import { useServerLanguage } from '../i18n'
import { LanguageMenu } from './I18n'
import { ErrorScreen } from './ErrorPage'
import { Logo, Mascot } from './Logo'
import { applyTheme, savedDark } from '../lib/theme'

const NAV = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/collection', label: 'Collection' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/import', label: 'Import / export' },
  { to: '/settings', label: 'Settings' },
]
const ADMIN_NAV = [
  { to: '/admin/users', label: 'Users' },
  { to: '/admin/jobs', label: 'Data sync' },
  { to: '/admin/checks', label: 'Data checks' },
]

function useTheme() {
  const [dark, setDark] = useState(savedDark)
  useEffect(() => applyTheme(dark, true), [dark])
  return [dark, setDark] as const
}

export function Layout() {
  const { t } = useTranslation()
  const me = useMe()
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [dark, setDark] = useTheme()
  const health = useHealth()
  useServerLanguage(me.data?.language)

  useEffect(
    () =>
      onSessionExpired(() => {
        client.clear()
        navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      }),
    [client, navigate, location],
  )

  if (me.isPending) {
    return <div className="flex h-screen items-center justify-center"><span className="loading loading-spinner loading-lg" /></div>
  }
  if (me.isError) {
    // Not logged in: the login page. Server down or failing: say so, with a retry.
    if (me.error instanceof ApiError && (me.error.status === 401 || me.error.status === 403)) {
      return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
    }
    return <ErrorScreen title={t('Something went wrong')} text={me.error.message} onRetry={() => me.refetch()} home={false} />
  }

  const logout = async () => {
    const { data } = await api.POST('/api/auth/logout', { body: {} })
    client.clear()
    const endSession = (data as { end_session_url?: string | null } | undefined)?.end_session_url
    if (endSession) window.location.href = endSession
    else navigate('/login')
  }

  const link = ({ isActive }: { isActive: boolean }) => (isActive ? 'menu-active' : '')
  const closeDrawer = () => {
    const toggle = document.getElementById('nav-drawer') as HTMLInputElement | null
    if (toggle) toggle.checked = false
  }

  return (
    <div className="drawer lg:drawer-open">
      <input id="nav-drawer" type="checkbox" className="drawer-toggle" />
      <div className="drawer-content flex min-h-screen flex-col">
        <header className="navbar sticky top-0 z-30 border-b border-base-300 bg-base-100/90 backdrop-blur">
          <label htmlFor="nav-drawer" className="btn btn-square btn-ghost lg:hidden" aria-label={t('Menu')}>
            <svg viewBox="0 0 24 24" className="h-6 w-6 fill-none stroke-current stroke-2"><path d="M4 6h16M4 12h16M4 18h16" /></svg>
          </label>
          <Link to="/" className="flex flex-1 items-center gap-2 px-2 font-display text-xl font-extrabold lg:hidden">
            <Mascot className="h-8 w-8 object-contain" />
            Zukan
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <LanguageMenu />
            <label className="swap swap-rotate btn btn-ghost btn-circle" title={t('Toggle theme')}>
              <input type="checkbox" checked={dark} onChange={(e) => setDark(e.target.checked)} />
              <svg className="swap-off h-5 w-5 fill-none stroke-current stroke-2" viewBox="0 0 24 24"><path d="M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z" /></svg>
              <svg className="swap-on h-5 w-5 fill-current" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79Z" /></svg>
            </label>
            <div className="dropdown dropdown-end">
              <button tabIndex={0} className="btn btn-ghost btn-sm">{me.data.username}</button>
              <ul tabIndex={0} className="menu dropdown-content z-40 w-44 rounded-box bg-base-200 p-2 shadow">
                <li><NavLink to="/settings">{t('Settings')}</NavLink></li>
                <li><button onClick={logout}>{t('Log out')}</button></li>
              </ul>
            </div>
          </div>
        </header>
        <main className="flex-1 p-4 lg:p-6">
          <Outlet />
        </main>
        {/* Publishers' notices (Riot Games, Wizards...) in full on the About page. */}
        <footer className="border-t border-base-300 px-4 py-3 text-xs text-base-content/50 lg:px-6">
          {t('Trademarks belong to their owners. Zukan is not affiliated with any game publisher.')}{' '}
          <Link to="/about" className="link">{t('About')}</Link>
        </footer>
      </div>
      <div className="drawer-side z-40">
        <label htmlFor="nav-drawer" className="drawer-overlay" aria-label={t('Close menu')} />
        <aside className="zukan-nav flex min-h-full w-60 flex-col bg-neutral text-neutral-content">
          <div className="px-5 py-5">
            <Link to="/" onClick={closeDrawer}><Logo onDark className="w-44" /></Link>
            <div className="mt-1 text-xs text-neutral-content/60"><span lang="ja">図鑑</span> · {t('card encyclopedia')}</div>
          </div>
          <ul className="menu w-full gap-1 px-3" onClick={closeDrawer}>
            {NAV.map((n) => (
              <li key={n.to}><NavLink to={n.to} end={n.end} className={link}>{t(n.label)}</NavLink></li>
            ))}
            {me.data.role === 'admin' && (
              <>
                <li className="menu-title mt-4">{t('Administration')}</li>
                {ADMIN_NAV.map((n) => (
                  <li key={n.to}><NavLink to={n.to} className={link}>{t(n.label)}</NavLink></li>
                ))}
              </>
            )}
          </ul>
          <div className="mt-auto flex gap-2 px-6 py-4 text-xs text-neutral-content/50">
            {health.data?.version && <span>v{health.data.version}</span>}
            <Link to="/about" className="link link-hover" onClick={closeDrawer}>{t('About')}</Link>
          </div>
        </aside>
      </div>
    </div>
  )
}
