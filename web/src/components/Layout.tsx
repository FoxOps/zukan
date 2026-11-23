import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { api, ApiError, call, onSessionExpired, serverDown } from '../api/client'
import { useAndroidRelease, useHealth, useMe } from '../api/queries'
import { useServerLanguage } from '../i18n'
import { LanguageMenu } from './I18n'
import { Icon, type IconName } from './Icon'
import { MaintenanceBanner, MaintenanceScreen } from './Maintenance'
import { showError } from './toast'
import { Logo } from './Logo'
import { useTheme } from '../lib/theme'
import { TYPE_TO_SEARCH_GLOBAL, useTypeToSearch } from '../lib/typeToSearch'

type NavItem = { to: string; label: string; icon: IconName; end?: boolean; module?: string }

// `module`: shown to users who can use that optional module (turned on or given by a group).
const COLLECTION_NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'home', end: true },
  { to: '/collection', label: 'Collection', icon: 'collection' },
  { to: '/catalog', label: 'Catalog', icon: 'search' },
  { to: '/binder', label: 'Binder', icon: 'binder', module: 'binder' },
  { to: '/decks', label: 'Decks', icon: 'decks', module: 'decks' },
  { to: '/finance', label: 'Finance', icon: 'chart' },
]
const WORKSPACE_NAV: NavItem[] = [
  { to: '/import', label: 'Import / export', icon: 'download' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]
const ADMIN_NAV: NavItem[] = [
  { to: '/admin/users', label: 'Users', icon: 'users' },
  { to: '/admin/groups', label: 'Groups', icon: 'groups' },
  { to: '/admin/jobs', label: 'Data sync', icon: 'sync' },
  { to: '/admin/checks', label: 'Data checks', icon: 'checks' },
  { to: '/admin/server', label: 'Server', icon: 'server' },
]
// Phones: the four quick places; "More" opens the whole menu.
const BOTTOM_NAV = COLLECTION_NAV.slice(0, 3)

function initials(name: string) {
  const parts = name.split(/[\s._-]+/).filter(Boolean)
  return ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? parts[0]?.[1] ?? '')).toUpperCase() || '?'
}

/** Search box of the top bar: always the catalog (any language), never a filter of the page. */
function CatalogSearchBox() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  return (
    <form
      role="search"
      className="hidden max-w-md flex-1 md:flex"
      onSubmit={(e) => {
        e.preventDefault()
        const q = text.trim()
        navigate(q ? `/catalog?q=${encodeURIComponent(q)}` : '/catalog')
        setText('')
      }}
    >
      <label className="input w-full border-transparent bg-base-200">
        <Icon name="search" className="h-4 w-4 opacity-70" />
        <input
          {...TYPE_TO_SEARCH_GLOBAL}
          type="search"
          enterKeyHint="search"
          aria-label={t('Search the catalog')}
          placeholder={t('Search the catalog in any language…')}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
      </label>
    </form>
  )
}

export function Layout() {
  const { t } = useTranslation()
  const me = useMe()
  const location = useLocation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [dark, setDark] = useTheme()
  const [loggingOut, setLoggingOut] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuOpener = useRef<HTMLElement | null>(null)
  const drawer = useRef<HTMLElement>(null)
  const health = useHealth()
  const android = useAndroidRelease()
  useServerLanguage(me.data?.language, me.data?.language_chosen)
  useTypeToSearch()
  const maintenance = health.data?.maintenance ?? null
  // Maintenance over: reload what failed meanwhile.
  const wasInMaintenance = useRef(false)
  useEffect(() => {
    if (wasInMaintenance.current && !maintenance) client.invalidateQueries()
    wasInMaintenance.current = !!maintenance
  }, [maintenance, client])
  // Users: the server answers its maintenance page instead of the interface (it comes back
  // by itself); administrators keep the interface, with a notice.
  const role = me.data?.role
  useEffect(() => {
    if (maintenance && role && role !== 'admin') window.location.reload()
  }, [maintenance, role])

  // Server back: reload what failed meanwhile.
  const backOnline = useCallback(() => void client.invalidateQueries(), [client])

  useEffect(
    () =>
      onSessionExpired(() => {
        client.clear()
        navigate(`/login?next=${encodeURIComponent(location.pathname + location.search)}`)
      }),
    [client, navigate, location],
  )

  // Menu drawer (below the large breakpoint): Escape closes it, the focus goes back to the
  // button that opened it.
  const closeMenu = useCallback(() => {
    setMenuOpen(false)
    menuOpener.current?.focus()
  }, [])
  const openMenu = (e: React.MouseEvent<HTMLElement>) => {
    menuOpener.current = e.currentTarget
    setMenuOpen(true)
  }
  useEffect(() => {
    if (!menuOpen) return
    drawer.current?.querySelector<HTMLElement>('a, button')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen, closeMenu])

  if (me.isPending) {
    return <div className="flex h-screen items-center justify-center"><span className="loading loading-spinner loading-lg" /></div>
  }
  if (me.isError) {
    // Not logged in: the login page. Server down or failing: the maintenance page, which
    // comes back by itself.
    if (me.error instanceof ApiError && (me.error.status === 401 || me.error.status === 403)) {
      return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
    }
    return <MaintenanceScreen onBack={backOnline} />
  }
  // Server stopped answering (restart, update): the maintenance page until it is back.
  if (health.isError && serverDown(health.error)) return <MaintenanceScreen onBack={backOnline} />

  const logout = async () => {
    setLoggingOut(true)
    let data: unknown
    try {
      data = await call(api.POST('/api/auth/logout', { body: {} }))
    } catch (e) {
      // 401: no session left, signed out already. Otherwise not confirmed by the server: the
      // session may still be valid, never claim it ended.
      if (!(e instanceof ApiError && e.status === 401)) {
        setLoggingOut(false)
        showError(t('Logging out failed: you are still signed in. {{reason}}', { reason: (e as Error).message }))
        return
      }
    }
    client.clear()
    const endSession = (data as { end_session_url?: string | null } | undefined)?.end_session_url
    if (endSession) window.location.href = endSession
    // No provider logout: stay on the login page (single sign-on only would sign in
    // again at once with the provider's session).
    else navigate('/login?logged_out=1')
  }

  const allowed = (n: NavItem) => !n.module || me.data.modules?.includes(n.module)
  const isAdmin = me.data.role === 'admin'
  const navLink = (n: NavItem) => (
    <li key={n.to}>
      <NavLink
        to={n.to}
        end={n.end}
        className={({ isActive }) =>
          `flex min-h-11 items-center gap-3 rounded-xl px-3.5 py-2.5 text-[15px] ${
            isActive ? 'bg-primary font-semibold text-primary-content' : 'hover:bg-white/10'
          }`
        }
      >
        <Icon name={n.icon} />
        {t(n.label)}
      </NavLink>
    </li>
  )
  const group = (label: string) => (
    <li className="mx-3 mb-2 mt-5 text-[10px] font-semibold uppercase tracking-[0.13em] text-neutral-content/70" role="presentation">
      {label}
    </li>
  )

  const themeToggle = (
    <button
      type="button"
      className="btn btn-square btn-ghost min-h-11 min-w-11"
      onClick={() => setDark(!dark)}
      aria-label={dark ? t('Use the light theme') : t('Use the dark theme')}
      title={t('Toggle theme')}
    >
      <Icon name={dark ? 'sun' : 'moon'} />
    </button>
  )

  return (
    // Large screens: the sidebar is a column of the page, as long as the page (no scrollbar of
    // its own). Elsewhere it is a drawer over the page.
    <div className="min-h-screen bg-base-200 lg:flex">
      {/* Sidebar: fixed column on large screens, a drawer elsewhere. */}
      {menuOpen && <div className="fixed inset-0 z-40 bg-neutral/60 lg:hidden" onClick={closeMenu} aria-hidden="true" />}
      <aside
        ref={drawer}
        aria-label={t('Main navigation')}
        // A page opened from the menu closes it.
        onClick={(e) => (e.target as HTMLElement).closest('a[href^="/"]') && setMenuOpen(false)}
        className={`fixed inset-y-0 left-0 z-50 flex w-60 shrink-0 flex-col overflow-y-auto bg-neutral px-4 py-6 text-neutral-content transition-transform [scrollbar-width:none] motion-reduce:transition-none lg:static lg:z-auto lg:translate-x-0 lg:overflow-visible ${
          menuOpen ? 'translate-x-0' : '-translate-x-full max-lg:invisible'
        }`}
      >
        <div className="flex items-start justify-between px-2.5 pb-6">
          <Link to="/" aria-label={t('Overview')}>
            <Logo onDark className="w-[180px] max-w-full" />
          </Link>
          <button type="button" className="btn btn-square btn-ghost btn-sm text-neutral-content lg:hidden" onClick={closeMenu} aria-label={t('Close menu')}>
            <Icon name="close" />
          </button>
        </div>
        <div className="-mt-3 mb-4 px-2.5 text-[11px] text-neutral-content/75">
          <span lang="ja">図鑑</span> · {t('Your card encyclopedia')}
        </div>
        <nav aria-label={t('Main navigation')}>
          <ul className="flex flex-col gap-1">
            {COLLECTION_NAV.filter(allowed).map(navLink)}
            {group(t('Workspace'))}
            {WORKSPACE_NAV.map(navLink)}
            {isAdmin && (
              <>
                {group(t('Administration'))}
                {ADMIN_NAV.map(navLink)}
              </>
            )}
          </ul>
        </nav>
        <div className="mt-auto flex flex-col gap-2 px-3 pt-6 text-xs text-neutral-content/75">
          {/* Phones: the language is chosen here (no room in the top bar). */}
          <div className="sm:hidden">
            <LanguageMenu up />
          </div>
          {android.data && (
            <a href={android.data.url} className="link link-hover flex min-h-8 items-center gap-1.5" title={t('Download the Android app')}>
              <Icon name="download" className="h-4 w-4" />
              {t('Android app {{version}}', { version: android.data.version })}
            </a>
          )}
          <div className="flex gap-2">
            {health.data?.version && <span>v{health.data.version}</span>}
            <Link to="/about" className="link link-hover">{t('About')}</Link>
          </div>
        </div>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center gap-2 border-b border-base-300 bg-base-100 px-3 sm:gap-4 sm:px-6 lg:h-[76px] lg:px-9">
          <button type="button" className="btn btn-square btn-ghost min-h-11 min-w-11 lg:hidden" onClick={openMenu} aria-label={t('Menu')} aria-expanded={menuOpen}>
            <Icon name="menu" />
          </button>
          <Link to="/" className="lg:hidden" aria-label={t('Overview')}>
            <Logo className="w-[150px] min-[380px]:w-[180px]" />
          </Link>
          <CatalogSearchBox />
          <div className="ml-auto flex items-center gap-1 sm:gap-2">
            <div className="hidden sm:block">
              <LanguageMenu />
            </div>
            {themeToggle}
            <div className="dropdown dropdown-end">
              <button tabIndex={0} type="button" className="btn btn-ghost min-h-11 gap-2 px-1 sm:px-2" aria-label={t('Account')}>
                <span className="grid h-9 w-9 place-items-center rounded-full bg-neutral text-xs font-semibold text-neutral-content">
                  {initials(me.data.username)}
                </span>
                <span className="hidden max-w-40 truncate font-semibold md:inline">{me.data.username}</span>
              </button>
              <ul tabIndex={0} className="menu dropdown-content z-40 mt-2 w-52 rounded-box border border-base-300 bg-base-100 p-2 shadow">
                <li className="menu-title truncate">{me.data.username}</li>
                <li><NavLink to="/settings"><Icon name="settings" className="h-4 w-4" />{t('Settings')}</NavLink></li>
                <li><Link to="/about"><Icon name="info" className="h-4 w-4" />{t('About')}</Link></li>
                <li>
                  <button type="button" onClick={logout} disabled={loggingOut}>
                    <Icon name="logout" className="h-4 w-4" />
                    {t('Log out')}
                  </button>
                </li>
              </ul>
            </div>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1480px] flex-1 px-4 pb-28 pt-6 sm:px-6 lg:px-9 lg:pb-10 lg:pt-8">
          {maintenance && <MaintenanceBanner state={maintenance} />}
          <Outlet />
        </main>
        {/* Publishers' notices (Riot Games, Wizards...) in full on the About page. */}
        <footer className="border-t border-base-300 px-4 pb-24 pt-4 text-xs text-base-content/70 sm:px-6 lg:px-9 lg:pb-4">
          {t('Trademarks belong to their owners. Zukan is not affiliated with any game publisher.')}{' '}
          <Link to="/about" className="link">{t('About')}</Link>
        </footer>
      </div>

      <nav
        aria-label={t('Quick navigation')}
        className="fixed inset-x-0 bottom-0 z-30 flex justify-around border-t border-base-300 bg-base-100 px-2 pb-[max(0.375rem,env(safe-area-inset-bottom))] pt-1.5 lg:hidden"
      >
        {BOTTOM_NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              `flex min-h-[54px] min-w-16 flex-col items-center justify-center gap-1 px-3 text-[11px] font-semibold ${
                isActive ? 'text-secondary shadow-[inset_0_-3px_0_var(--color-primary)]' : ''
              }`
            }
          >
            <Icon name={n.icon} className="h-[21px] w-[21px]" />
            {t(n.label)}
          </NavLink>
        ))}
        <button
          type="button"
          className="flex min-h-[54px] min-w-16 flex-col items-center justify-center gap-1 px-3 text-[11px] font-semibold"
          onClick={openMenu}
          aria-expanded={menuOpen}
        >
          <Icon name="more" className="h-[21px] w-[21px]" />
          {t('More')}
        </button>
      </nav>
    </div>
  )
}
