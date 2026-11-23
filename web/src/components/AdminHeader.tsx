import { useTranslation } from 'react-i18next'
import { NavLink } from 'react-router'
import { PageHeader } from './Page'

const PAGES = [
  { to: '/admin/users', label: 'Users' },
  { to: '/admin/groups', label: 'Groups' },
  { to: '/admin/jobs', label: 'Data sync' },
  { to: '/admin/checks', label: 'Data checks' },
  { to: '/admin/server', label: 'Server' },
]

/** Top of the administration pages: title and the tabs between them. */
export function AdminHeader({ title }: { title: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow={t('Administration')} title={title} subtitle={t('Manage data and access without leaving your collection workspace.')} />
      <nav aria-label={t('Administration')} className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        {PAGES.map((p) => (
          <NavLink
            key={p.to}
            to={p.to}
            className={({ isActive }) => `btn min-h-11 shrink-0 rounded-xl ${isActive ? 'btn-neutral shadow-[inset_0_-3px_0_var(--color-primary)]' : ''}`}
          >
            {t(p.label)}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
