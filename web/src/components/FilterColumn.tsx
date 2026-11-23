import { useEffect, useRef, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import type { FilterSheet as Sheet } from '../lib/filterSheet'
import { Icon } from './Icon'

/** "Filters" button next to the search field, below the large-screen breakpoint only. */
export function FiltersButton({ sheet, active = 0 }: { sheet: Sheet; active?: number }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className="btn min-h-11 gap-2 lg:hidden"
      aria-expanded={sheet.open}
      aria-controls="filter-column"
      onClick={sheet.show}
    >
      <Icon name="filter" />
      {t('Filters')}
      {active > 0 && <span className="badge badge-primary badge-sm">{active}</span>}
    </button>
  )
}

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea, summary, [tabindex]:not([tabindex="-1"])'

/** Filter column of Catalog and Collection: beside the results on large screens, a sheet
 * from the bottom elsewhere (Escape or the backdrop close it, the focus stays inside). */
export function FilterColumn({ sheet, onReset, canReset, children }: { sheet: Sheet; onReset: () => void; canReset: boolean; children: ReactNode }) {
  const { t } = useTranslation()
  const panel = useRef<HTMLElement>(null)
  const { open, close } = sheet
  useEffect(() => {
    if (!open) return
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    const onKey = (e: KeyboardEvent) => {
      // Escape inside an open list (searchable select) closes that list first.
      if (e.key === 'Escape' && !e.defaultPrevented) close()
      if (e.key !== 'Tab' || !panel.current) return
      const items = Array.from(panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null)
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, close])

  return (
    <>
      {open && <div className="fixed inset-0 z-40 bg-neutral/50 lg:hidden" onClick={close} aria-hidden="true" />}
      <aside
        ref={panel}
        id="filter-column"
        aria-label={t('Card filters')}
        role={open ? 'dialog' : undefined}
        aria-modal={open ? true : undefined}
        className={`flex-col gap-4 border-base-300 bg-base-100 p-5 lg:sticky lg:top-24 lg:flex lg:h-fit lg:w-60 lg:shrink-0 lg:rounded-2xl lg:border ${
          open ? 'fixed inset-x-0 bottom-0 z-50 flex max-h-[85vh] overflow-y-auto rounded-t-[20px] border-t pb-[max(1.25rem,env(safe-area-inset-bottom))] lg:static lg:max-h-none lg:overflow-visible' : 'hidden'
        }`}
      >
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base">{t('Filters')}</h2>
          <div className="flex items-center gap-1">
            <button type="button" className="btn btn-ghost btn-sm" disabled={!canReset} onClick={onReset}>
              {t('Reset')}
            </button>
            <button type="button" className="btn btn-square btn-ghost btn-sm lg:hidden" onClick={close} aria-label={t('Close filters')}>
              <Icon name="close" />
            </button>
          </div>
        </div>
        {children}
        <button type="button" className="btn btn-primary min-h-11 lg:hidden" onClick={close}>
          {t('Show results')}
        </button>
      </aside>
    </>
  )
}

/** One labelled filter of the column. */
export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-xs font-semibold">{label}</span>
      {children}
    </div>
  )
}

/** Labelled group that opens on demand (game-specific attributes); open by itself when one of
 * its filters is in use, so an active filter is never hidden. */
export function FilterGroup({ label, active, children }: { label: string; active: boolean; children: ReactNode }) {
  return (
    <details className="group" open={active || undefined}>
      <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 text-sm font-semibold [&::-webkit-details-marker]:hidden">
        <Icon name="chevron" className="h-4 w-4 transition-transform group-open:rotate-90 motion-reduce:transition-none" />
        {label}
      </summary>
      <div className="flex flex-col gap-4 pt-2">{children}</div>
    </details>
  )
}

/** "N filters in use · Clear all" above the results. */
export function ActiveFilters({ count, onClear }: { count: number; onClear: () => void }) {
  const { t } = useTranslation()
  if (!count) return null
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-base-300 bg-base-200 px-4 py-2 text-sm">
      <Icon name="filter" className="h-4 w-4" />
      <span>{t('{{count}} filters in use', { count })}</span>
      <button type="button" className="btn btn-ghost btn-sm ml-auto" onClick={onClear}>
        {t('Clear filters')}
      </button>
    </div>
  )
}
