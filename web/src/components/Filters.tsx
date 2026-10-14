import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, call } from '../api/client'
import { useGames, useSets, type Game } from '../api/queries'
import { languageName } from '../lib/format'
import { ColorSymbol } from './ColorBadges'
import { Select } from './Select'

type GameTabsProps = {
  value: string
  onChange: (id: string) => void
  allowAll?: boolean
  // Games to show (user settings); all when null or undefined.
  only?: string[] | null
}

export function GameTabs({ value, onChange, allowAll = true, only }: GameTabsProps) {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const shown = only ? games.filter((g) => only.includes(g.id)) : games
  return (
    <div role="tablist" className="tabs tabs-box w-fit">
      {allowAll && shown.length > 1 && (
        <button role="tab" className={`tab ${value === '' ? 'tab-active' : ''}`} onClick={() => onChange('')}>
          {t('All games')}
        </button>
      )}
      {shown.map((g) => (
        <button key={g.id} role="tab" className={`tab ${value === g.id ? 'tab-active' : ''}`} onClick={() => onChange(g.id)}>
          {g.name}
        </button>
      ))}
    </div>
  )
}

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (q: string) => void; placeholder: string }) {
  const [text, setText] = useState(value)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const type = (next: string) => {
    setText(next)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => onChange(next), 300)
  }
  return (
    <label className="input w-full sm:w-72">
      <svg viewBox="0 0 24 24" className="h-4 w-4 fill-none stroke-current stroke-2 opacity-60"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
      <input type="search" placeholder={placeholder} value={text} onChange={(e) => type(e.target.value)} />
    </label>
  )
}

export function SetSelect({ game, value, onChange }: { game: string; value: string; onChange: (id: string) => void }) {
  const { t } = useTranslation()
  const { data: sets = [] } = useSets(game || null)
  if (!game) return null
  return (
    <Select
      className="w-full sm:w-64"
      value={value}
      onChange={onChange}
      aria-label={t('Set')}
      options={[
        { value: '', label: t('All sets') },
        ...sets.map((s) => ({
          value: String(s.id),
          label: `${s.code} - ${s.name}${s.lang ? ` (${languageName(s.lang)})` : ''}`,
        })),
      ]}
    />
  )
}

export function ColorFilter({ game, value, onChange }: { game?: Game; value: string[]; onChange: (colors: string[]) => void }) {
  const { t } = useTranslation()
  if (!game) return null
  const toggle = (code: string) =>
    onChange(value.includes(code) ? value.filter((c) => c !== code) : [...value, code])
  return (
    <div className="flex flex-wrap items-center gap-1">
      {game.colors.map((c) => {
        const active = value.includes(c.code)
        if (c.icon) {
          return (
            <button
              key={c.code}
              className={`btn btn-circle btn-sm btn-ghost p-1 transition ${active ? 'bg-base-300 ring-2 ring-primary' : 'opacity-50 hover:opacity-100'}`}
              aria-pressed={active}
              onClick={() => toggle(c.code)}
            >
              <ColorSymbol color={c} />
            </button>
          )
        }
        return (
          <button
            key={c.code}
            className={`badge cursor-pointer border-2 transition ${active ? 'text-white [text-shadow:0_0_2px_#000]' : 'badge-outline opacity-70'}`}
            style={active ? { backgroundColor: c.hex, borderColor: c.hex } : { borderColor: c.hex }}
            aria-pressed={active}
            onClick={() => toggle(c.code)}
          >
            {t(c.name)}
          </button>
        )
      })}
    </div>
  )
}

/** Game-specific filters (types, rarity...), as `key:value` pairs. */
export function AdvancedFilters({ game, value, onChange }: { game?: Game; value: string[]; onChange: (attrs: string[]) => void }) {
  const { t } = useTranslation()
  const values = useQuery({
    queryKey: ['filters', game?.id],
    queryFn: () => call(api.GET('/api/games/{game_id}/filters', { params: { path: { game_id: game!.id } } })),
    enabled: !!game?.filters.length,
    staleTime: 60 * 60_000,
  })
  if (!game?.filters.length) return null
  const chosen = new Map(value.map((v) => [v.slice(0, v.indexOf(':')), v.slice(v.indexOf(':') + 1)]))
  const pick = (key: string, picked: string) => {
    const next = new Map(chosen)
    if (picked) next.set(key, picked)
    else next.delete(key)
    onChange([...next].map(([k, v]) => `${k}:${v}`))
  }
  return (
    <div className="flex flex-wrap items-end gap-3">
      {game.filters.map((f) => (
        <label key={f.key} className="fieldset py-0">
          <span className="fieldset-legend pb-1 pt-0 text-xs">{t(f.label)}</span>
          <Select
            className="select-sm w-48"
            value={chosen.get(f.key) ?? ''}
            onChange={(v) => pick(f.key, v)}
            options={[{ value: '', label: t('Any') }, ...(values.data?.[f.key] ?? []).map((v) => ({ value: v, label: v }))]}
          />
        </label>
      ))}
      {chosen.size > 0 && (
        <button className="btn btn-ghost btn-sm" onClick={() => onChange([])}>
          {t('Clear filters')}
        </button>
      )}
    </div>
  )
}
