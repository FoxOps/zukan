import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Icon } from './Icon'
import { Mascot } from './Logo'

/** Top of a page: small green eyebrow, title, one line on what the page is for, and at most
 * one primary action for the whole page. */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  action,
}: {
  eyebrow?: ReactNode
  title: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="mb-2 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-secondary">{eyebrow}</div>}
        <h1 className="break-words text-3xl leading-tight lg:text-4xl">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-base-content/70">{subtitle}</p>}
      </div>
      {action && <div className="flex w-full flex-wrap gap-2 sm:w-auto [&>*]:max-sm:flex-1">{action}</div>}
    </div>
  )
}

/** A section of a page: paper surface, 20px corners, an optional title row with one link or
 * small control on its right. */
export function Panel({
  title,
  subtitle,
  aside,
  children,
  className = '',
  bodyClassName = '',
  as: Tag = 'section',
  ...rest
}: {
  title?: ReactNode
  subtitle?: ReactNode
  aside?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
  as?: 'section' | 'div' | 'aside'
} & Omit<React.HTMLAttributes<HTMLElement>, 'title'>) {
  return (
    <Tag className={`min-w-0 rounded-[20px] border border-base-300 bg-base-100 p-5 sm:p-6 ${className}`} {...rest}>
      {(title || aside) && (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            {title && <h2 className="text-xl">{title}</h2>}
            {subtitle && <p className="mt-1 text-xs text-base-content/70">{subtitle}</p>}
          </div>
          {aside && <div className="flex flex-wrap items-center gap-2">{aside}</div>}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </Tag>
  )
}

/** "View all →" style link of a panel title row. */
export function PanelLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="btn btn-ghost btn-sm gap-1">
      {children}
      <Icon name="arrow" className="h-3.5 w-3.5" />
    </Link>
  )
}

/** One key figure: label, big tabular value, and a line or link under it. The lead metric of
 * a row gets the gold top edge. */
export function Metric({
  label,
  value,
  children,
  lead = false,
  className = '',
}: {
  label: ReactNode
  value: ReactNode
  children?: ReactNode
  lead?: boolean
  className?: string
}) {
  return (
    <div className={`min-w-0 rounded-2xl border border-base-300 bg-base-100 px-6 py-5 ${lead ? 'border-t-4 border-t-primary' : ''} ${className}`}>
      <div className="text-xs text-base-content/70">{label}</div>
      <div className="my-1 break-words font-display text-3xl font-extrabold tabular-nums">{value}</div>
      {children && <div className="flex flex-col gap-1 text-xs text-base-content/70">{children}</div>}
    </div>
  )
}

/** One actionable empty or failure state instead of empty charts and tables. */
export function EmptyState({ title, children, actions }: { title: ReactNode; children?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-[20px] border border-base-300 bg-base-100 px-6 py-12 text-center">
      <Mascot className="h-16 w-16 object-contain" />
      <h2 className="text-2xl">{title}</h2>
      {children && <div className="max-w-lg text-base-content/70">{children}</div>}
      {actions && <div className="mt-2 flex flex-wrap justify-center gap-2">{actions}</div>}
    </div>
  )
}

/** Top of a dialog: eyebrow, title, a line of details and the close button (inside a
 * `<dialog>`, it closes it). */
export function DialogHeader({ eyebrow, title, children }: { eyebrow?: ReactNode; title: ReactNode; children?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className="mb-5 flex items-start justify-between gap-3">
      <div className="min-w-0">
        {eyebrow && <Eyebrow className="mb-1.5">{eyebrow}</Eyebrow>}
        <h3 className="break-words text-2xl">{title}</h3>
        {children && <div className="mt-1 flex flex-wrap items-center gap-1 text-sm text-base-content/70">{children}</div>}
      </div>
      <form method="dialog">
        <button className="btn btn-square btn-ghost min-h-11 min-w-11" aria-label={t('Close')}>
          <Icon name="close" />
        </button>
      </form>
    </div>
  )
}

/** Small uppercase label above a group of fields or links. */
export function Eyebrow({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`text-[11px] font-semibold uppercase tracking-[0.12em] text-secondary ${className}`}>{children}</div>
}
