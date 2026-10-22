import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useGames, useMe } from '../../api/queries'
import { Pagination } from '../../components/Pagination'
import { Select } from '../../components/Select'
import { useToast } from '../../components/toast'
import { formatDate, formatDateTime } from '../../lib/format'
import { useUrlState } from '../../lib/hooks'

const PAGE_SIZE = 50
// Secondary catalog sources by id.
const SOURCES: Record<string, string> = {
  mtgjson: 'MTGJSON',
  tcgcsv: 'tcgcsv (TCGplayer)',
  tcgapi_eu: 'TCG API (tcg-api.eu)',
  apitcg: 'API TCG (apitcg.com)',
}
// Fields an arbitration can write (others can only be kept as they are).
const WRITABLE = new Set(['name', 'rarity', 'set name', 'release date', 'card count'])
const REASONS: Record<string, string> = {
  not_seen: 'Missed by the last catalog sync',
  no_image: 'No image',
  no_attributes: 'No card details',
}

type Discrepancy = Schemas['DiscrepancyOut']
type Choice = 'primary' | 'secondary' | 'custom' | null

/** Data checks: differences between catalog sources (with arbitration) and stale cards. */
export default function Checks() {
  const { t } = useTranslation()
  const me = useMe()
  const url = useUrlState()
  if (me.data?.role !== 'admin') return me.data ? <Navigate to="/" replace /> : null
  const tab = url.get('tab') === 'stale' ? 'stale' : 'differences'
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Data checks')}</h1>
      <div role="tablist" className="tabs tabs-box w-fit">
        <button role="tab" className={`tab ${tab === 'differences' ? 'tab-active' : ''}`} onClick={() => url.set({ tab: null, game: null, source: null, field: null, state: null })}>
          {t('Source differences')}
        </button>
        <button role="tab" className={`tab ${tab === 'stale' ? 'tab-active' : ''}`} onClick={() => url.set({ tab: 'stale', game: null, source: null, field: null, state: null })}>
          {t('Stale cards')}
        </button>
      </div>
      {tab === 'stale' ? <StaleCards /> : <Differences />}
    </div>
  )
}

function Differences() {
  const { t } = useTranslation()
  const url = useUrlState()
  const toast = useToast()
  const client = useQueryClient()
  const { data: games = [] } = useGames()
  const game = url.get('game')
  const source = url.get('source')
  const field = url.get('field')
  const state = url.get('state') === 'resolved' ? 'resolved' : 'open'
  const checks = useQuery({
    queryKey: ['discrepancies', game, source, field, state, url.page],
    queryFn: () =>
      call(
        api.GET('/api/admin/discrepancies', {
          params: {
            query: {
              game: game || undefined,
              source: source || undefined,
              field: field || undefined,
              state,
              page: url.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  })
  const done = () => client.invalidateQueries({ queryKey: ['discrepancies'] })
  const resolve = useMutation({
    mutationFn: ({ id, choice, value }: { id: number; choice: Choice; value?: string }) =>
      call(api.POST('/api/admin/discrepancies/{discrepancy_id}/resolve', { params: { path: { discrepancy_id: id } }, body: { choice, value: value ?? null } })),
    onSuccess: (_, { choice }) => {
      toast(choice ? t('Choice saved, kept after every sync') : t('Difference open again'))
      return done()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const setRule = useMutation({
    mutationFn: (body: { game_id: string; source: string; field: string; prefer: 'primary' | 'secondary' }) =>
      call(api.PUT('/api/admin/discrepancies/rules', { body })),
    onSuccess: () => {
      toast(t('Rule saved: applied now and after every sync'))
      return done()
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const dropRule = useMutation({
    mutationFn: (id: number) => call(api.DELETE('/api/admin/discrepancies/rules/{rule_id}', { params: { path: { rule_id: id } } })),
    onSuccess: () => {
      toast(t('Rule removed'), 'info')
      return done()
    },
    onError: (e) => toast(e.message, 'error'),
  })

  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const filtered = !!(game || source || field)
  const custom = (d: Discrepancy) => {
    const value = window.prompt(t('Value to keep for {{field}}', { field: t(d.field) }), d.resolved_value ?? d.secondary_value ?? '')
    if (value?.trim()) resolve.mutate({ id: d.id, choice: 'custom', value: value.trim() })
  }
  const busy = resolve.isPending || setRule.isPending || dropRule.isPending

  return (
    <>
      <p className="text-sm text-base-content/70">
        {t('After each catalog refresh, second sources are compared with the main one. They fill missing data; where they disagree, the main source is kept unless you choose otherwise. Choices are kept after every sync.')}
      </p>

      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table table-sm">
          <thead>
            <tr>
              <th>{t('Game')}</th>
              <th>{t('Source')}</th>
              <th>{t('Field')}</th>
              <th className="text-right">{t('Open')}</th>
              <th className="text-right">{t('Arbitrated')}</th>
              <th>{t('Rule for this field')}</th>
            </tr>
          </thead>
          <tbody>
            {checks.data?.counts.length === 0 && (
              <tr>
                <td colSpan={6} className="text-base-content/60">{t('No difference found.')}</td>
              </tr>
            )}
            {checks.data?.counts.map((c) => {
              const active = c.game_id === game && c.source === source && c.field === field
              const pick = () => url.set(active ? { game: null, source: null, field: null } : { game: c.game_id, source: c.source, field: c.field })
              return (
                <tr key={`${c.game_id}-${c.source}-${c.field}`} className={`hover:bg-base-200 ${active ? 'bg-base-200 font-semibold' : ''}`}>
                  <td className="cursor-pointer" onClick={pick}>{gameName(c.game_id)}</td>
                  <td className="cursor-pointer" onClick={pick}>{SOURCES[c.source] ?? c.source}</td>
                  <td className="cursor-pointer" onClick={pick}>{t(c.field)}</td>
                  <td className="cursor-pointer text-right" onClick={pick}>{c.count.toLocaleString()}</td>
                  <td className="cursor-pointer text-right" onClick={pick}>{c.resolved.toLocaleString()}</td>
                  <td>
                    <Select
                      className="select-xs w-52"
                      value={c.rule ?? ''}
                      disabled={busy}
                      aria-label={t('Rule for this field')}
                      onChange={(v) => {
                        if (!v && c.rule_id) dropRule.mutate(c.rule_id)
                        else if (v) setRule.mutate({ game_id: c.game_id, source: c.source, field: c.field, prefer: v as 'primary' | 'secondary' })
                      }}
                      options={[
                        { value: '', label: t('Decide one by one') },
                        { value: 'primary', label: t('Always the main source') },
                        ...(WRITABLE.has(c.field) ? [{ value: 'secondary', label: t('Always the second source') }] : []),
                      ]}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3">
            <div role="tablist" className="tabs tabs-sm tabs-border">
              <button role="tab" className={`tab ${state === 'open' ? 'tab-active' : ''}`} onClick={() => url.set({ state: null })}>{t('Open')}</button>
              <button role="tab" className={`tab ${state === 'resolved' ? 'tab-active' : ''}`} onClick={() => url.set({ state: 'resolved' })}>{t('Arbitrated')}</button>
            </div>
            {checks.data && <span className="text-sm text-base-content/60">{t('{{count}} differences', { count: checks.data.total })}</span>}
            {checks.isPlaceholderData && <span className="loading loading-spinner loading-xs" />}
          </div>
          {filtered && (
            <button className="btn btn-ghost btn-sm" onClick={() => url.set({ game: null, source: null, field: null })}>
              {t('Show all')}
            </button>
          )}
        </div>
        {checks.data && checks.data.total > 0 && (
          <>
            <div className="overflow-x-auto rounded-box border border-base-300">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th>{t('Set')}</th>
                    <th>{t('Card')}</th>
                    <th>{t('Field')}</th>
                    <th>{t('Main source')}</th>
                    <th>{t('Second source')}</th>
                    <th>{state === 'open' ? t('Since') : t('Kept')}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {checks.data.items.map((d) => {
                    const kept = d.resolution === 'custom' ? d.resolved_value : d.resolution === 'secondary' ? d.secondary_value : d.primary_value
                    return (
                      <tr key={d.id}>
                        <td className="whitespace-nowrap">
                          <span className="font-mono text-xs">{d.set_code}</span> {d.set_name}
                        </td>
                        <td>
                          {d.card_id ? (
                            <Link className="link link-hover" to={`/cards/${d.card_id}`}>
                              {d.card_name} <span className="text-base-content/60">#{d.collector_number}</span>
                            </Link>
                          ) : (
                            <span className="text-base-content/60">{t('(set)')}</span>
                          )}
                        </td>
                        <td>{t(d.field)}</td>
                        <td className={d.resolution && d.resolution !== 'primary' ? 'line-through text-base-content/50' : ''}>{d.primary_value}</td>
                        <td className={d.resolution === 'secondary' ? 'font-semibold text-success' : 'text-warning'}>{d.secondary_value}</td>
                        <td className="whitespace-nowrap">
                          {state === 'open' ? (
                            formatDate(d.first_seen)
                          ) : (
                            <span title={formatDateTime(d.resolved_at)}>
                              {kept}
                              {d.by_rule && <span className="badge badge-ghost badge-xs ml-1">{t('rule')}</span>}
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap text-right">
                          {state === 'open' ? (
                            <div className="join">
                              <button className="btn join-item btn-xs" disabled={busy} onClick={() => resolve.mutate({ id: d.id, choice: 'primary' })}>
                                {t('Keep main')}
                              </button>
                              {WRITABLE.has(d.field) && (
                                <>
                                  <button className="btn join-item btn-xs" disabled={busy} onClick={() => resolve.mutate({ id: d.id, choice: 'secondary' })}>
                                    {t('Use second')}
                                  </button>
                                  <button className="btn join-item btn-xs" disabled={busy} onClick={() => custom(d)}>
                                    {t('Edit')}
                                  </button>
                                </>
                              )}
                            </div>
                          ) : (
                            !d.by_rule && (
                              <button className="btn btn-ghost btn-xs" disabled={busy} onClick={() => resolve.mutate({ id: d.id, choice: null })}>
                                {t('Reopen')}
                              </button>
                            )
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex justify-center">
              <Pagination page={url.page} pageSize={PAGE_SIZE} total={checks.data.total} onChange={url.goToPage} />
            </div>
          </>
        )}
      </div>
    </>
  )
}

function StaleCards() {
  const { t } = useTranslation()
  const url = useUrlState()
  const toast = useToast()
  const client = useQueryClient()
  const { data: games = [] } = useGames()
  const game = url.get('game')
  const stale = useQuery({
    queryKey: ['stale', game, url.page],
    queryFn: () =>
      call(api.GET('/api/admin/stale', { params: { query: { game: game || undefined, page: url.page, page_size: PAGE_SIZE } } })),
    placeholderData: keepPreviousData,
  })
  const refreshOne = useMutation({
    mutationFn: (id: number) => call(api.POST('/api/admin/cards/{card_id}/refresh', { params: { path: { card_id: id } } })),
    onSuccess: (r) => {
      if (!r.updated) toast(t('The source did not return this card'), 'error')
      else if (r.stale) toast(t('Card updated, but the source still lacks some data'), 'info')
      else toast(t('Card updated'))
      return client.invalidateQueries({ queryKey: ['stale'] })
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const refreshAll = useMutation({
    mutationFn: (gameId: string) =>
      call(api.POST('/api/admin/jobs/{game_id}/{kind}', { params: { path: { game_id: gameId, kind: 'refresh' } } })),
    onSuccess: (_, gameId) => toast(t('{{kind}} job started for {{game}}', { kind: t('refresh'), game: gameId }), 'info'),
    onError: (e) => toast(e.message, 'error'),
  })
  const refreshable = new Set(stale.data?.refreshable ?? [])
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const shownGames = game ? [game] : [...refreshable]

  return (
    <>
      <p className="text-sm text-base-content/70">
        {t('Cards the last catalog sync did not see, or without image or details. They are fetched again when opened and by the refresh job every two days; refresh them here to do it now.')}
      </p>
      <div className="flex flex-wrap items-center gap-3">
        <Select
          className="w-56"
          value={game}
          onChange={(v) => url.set({ game: v })}
          aria-label={t('Game')}
          options={[{ value: '', label: t('All games') }, ...games.map((g) => ({ value: g.id, label: g.name }))]}
        />
        {shownGames
          .filter((g) => refreshable.has(g))
          .map((g) => (
            <button key={g} className="btn btn-sm" disabled={refreshAll.isPending} onClick={() => refreshAll.mutate(g)}>
              {t('Refresh all stale {{game}} cards', { game: gameName(g) })}
            </button>
          ))}
        {stale.data && <span className="text-sm text-base-content/60">{t('{{count}} cards', { count: stale.data.total })}</span>}
      </div>
      {stale.data && stale.data.total > 0 && (
        <>
          <div className="overflow-x-auto rounded-box border border-base-300">
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>{t('Card')}</th>
                  {!game && <th>{t('Game')}</th>}
                  <th>{t('Why')}</th>
                  <th>{t('Last seen')}</th>
                  <th>{t('Last refresh attempt')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {stale.data.items.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link className="link link-hover" to={`/cards/${c.id}`}>{c.name}</Link>
                      <div className="text-xs text-base-content/60">{t('{{count}} printings', { count: c.printing_count })}</div>
                    </td>
                    {!game && <td>{gameName(c.game_id)}</td>}
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {c.reasons.map((r) => (
                          <span key={r} className="badge badge-sm badge-warning badge-soft">{t(REASONS[r] ?? r)}</span>
                        ))}
                      </div>
                    </td>
                    <td className="whitespace-nowrap">{formatDateTime(c.last_seen_at)}</td>
                    <td className="whitespace-nowrap">{formatDateTime(c.refresh_attempted_at)}</td>
                    <td className="text-right">
                      {refreshable.has(c.game_id) && (
                        <button
                          className="btn btn-xs"
                          disabled={refreshOne.isPending}
                          onClick={() => refreshOne.mutate(c.id)}
                        >
                          {refreshOne.isPending && refreshOne.variables === c.id ? <span className="loading loading-spinner loading-xs" /> : t('Refresh')}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={stale.data.total} onChange={url.goToPage} />
          </div>
        </>
      )}
    </>
  )
}
