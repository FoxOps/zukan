import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { normalize } from '../lib/format'

export type Option = { value: string; label: string; lang?: string }

// Up to this many options a native select is quicker to use; longer lists get a filter box.
export const SEARCHABLE_FROM = 11

type SelectProps = {
  value: string
  onChange: (value: string) => void
  options: Option[]
  // Classes of the select box (width, size: `w-64`, `select-sm`).
  className?: string
  disabled?: boolean
  'aria-label'?: string
}

/** A select that turns into a searchable list when it has more than 10 options. */
export function Select(props: SelectProps) {
  const { value, onChange, options, className = '', disabled } = props
  if (options.length < SEARCHABLE_FROM) {
    return (
      <select
        className={`select ${className}`}
        value={value}
        disabled={disabled}
        aria-label={props['aria-label']}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value} lang={o.lang}>
            {o.label}
          </option>
        ))}
      </select>
    )
  }
  return <SearchableSelect {...props} />
}

function SearchableSelect({ value, onChange, options, className = '', disabled, ...rest }: SelectProps) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const list = useRef<HTMLUListElement>(null)
  const listId = useId()

  const shown = useMemo(() => {
    const words = normalize(query).split(/\s+/).filter(Boolean)
    if (!words.length) return options
    return options.filter((o) => {
      const text = normalize(o.label)
      return words.every((w) => text.includes(w))
    })
  }, [options, query])

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  useEffect(() => {
    list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  const show = () => {
    setQuery('')
    setActive(Math.max(0, options.findIndex((o) => o.value === value)))
    setOpen(true)
  }
  const pick = (option: Option | undefined) => {
    if (!option) return
    onChange(option.value)
    setOpen(false)
  }
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') setActive((i) => Math.min(i + 1, shown.length - 1))
    else if (e.key === 'ArrowUp') setActive((i) => Math.max(i - 1, 0))
    else if (e.key === 'Enter') pick(shown[active])
    else if (e.key === 'Escape') setOpen(false)
    else return
    e.preventDefault()
  }

  const current = options.find((o) => o.value === value)
  // Width classes (with their variants, e.g. "sm:w-64") size the wrapper, the rest styles the button.
  const tokens = className.split(/\s+/).filter(Boolean)
  const isWidth = (token: string) => /^([\w-]+:)*w-/.test(token)
  return (
    <div ref={root} className={`relative ${tokens.filter(isWidth).join(' ')}`}>
      <button
        type="button"
        className={`select w-full text-left ${tokens.filter((token) => !isWidth(token)).join(' ')}`}
        disabled={disabled}
        aria-label={rest['aria-label']}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => {
          if (!open && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault()
            show()
          }
        }}
      >
        <span className="truncate">{current?.label ?? ''}</span>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 flex w-full min-w-64 flex-col gap-1 rounded-box border border-base-300 bg-base-100 p-2 shadow-lg animate-in fade-in zoom-in-95 duration-100">
          <input
            autoFocus
            className="input input-sm w-full"
            placeholder={t('Filter…')}
            value={query}
            role="combobox"
            aria-controls={listId}
            aria-expanded
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={keys}
          />
          <ul ref={list} id={listId} role="listbox" className="menu max-h-72 w-full flex-nowrap overflow-y-auto p-0">
            {shown.map((o, i) => (
              <li key={o.value} role="option" aria-selected={o.value === value}>
                <button
                  type="button"
                  lang={o.lang}
                  data-active={i === active}
                  className={`${i === active ? 'menu-focus' : ''} ${o.value === value ? 'font-semibold' : ''}`}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => pick(o)}
                >
                  {o.label}
                </button>
              </li>
            ))}
            {!shown.length && <li className="px-3 py-2 text-sm text-base-content/60">{t('No match')}</li>}
          </ul>
        </div>
      )}
    </div>
  )
}
