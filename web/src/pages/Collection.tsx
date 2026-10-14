import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame, useGames } from '../api/queries'
import { useAdjust } from '../api/stock'
import { ConditionBadge, FinishBadge, LangFlag } from '../components/Badges'
import { ColorFilter, GameTabs, SearchInput, SetSelect } from '../components/Filters'
import { ItemDialog } from '../components/ItemDialog'
import { Pagination } from '../components/Pagination'
import { Select } from '../components/Select'
import { CONDITIONS, finishName, formatMoney, languageName } from '../lib/format'
import { useUrlState } from '../lib/hooks'

type Item = Schemas['ItemOut']
const PAGE_SIZE = 50
const SORTS = {
  name: 'Name',
  set: 'Newest sets',
  updated: 'Recently changed',
  quantity: 'Quantity',
  price_asc: 'Price: low to high',
  price_desc: 'Price: high to low',
} as const

export default function Collection() {
  const { t } = useTranslation()
  const url = useUrlState()
  const game = url.get('game')
  const gameInfo = useGame(game)
  const { data: games = [] } = useGames()
  const adjust = useAdjust()
  const [editing, setEditing] = useState<Item | null>(null)
  const filters = {
    game: game || undefined,
    q: url.get('q') || undefined,
    set_id: url.get('set') ? Number(url.get('set')) : undefined,
    color: url.getAll('color').length ? url.getAll('color') : undefined,
    finish: url.get('finish') || undefined,
    condition: (url.get('condition') || undefined) as Item['condition'] | undefined,
    language: url.get('language') || undefined,
    sort: (url.get('sort') || 'name') as keyof typeof SORTS,
  }

  const items = useQuery({
    queryKey: ['collection', filters, url.page],
    queryFn: () =>
      call(
        api.GET('/api/collection', {
          params: { query: { ...filters, condition: filters.condition as never, page: url.page, page_size: PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
  })

  const step = (item: Item, delta: 1 | -1) =>
    adjust.mutate({
      printing_id: item.printing_id,
      finish: item.finish,
      condition: item.condition as never,
      language: item.language,
      delta,
      source: 'web',
    })

  // Per currency: prices of different markets are never added up.
  const pageValues = new Map<string, number>()
  for (const i of items.data?.items ?? []) pageValues.set(i.currency, (pageValues.get(i.currency) ?? 0) + Number(i.total ?? 0))
  const pageValue = [...pageValues].map(([currency, total]) => formatMoney(total, currency)).join(' + ') || formatMoney(0)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-bold">{t('Collection')}</h1>
        <Link to="/catalog" className="btn btn-primary btn-sm">{t('Add cards from the catalog')}</Link>
      </div>
      <GameTabs value={game} onChange={(id) => url.set({ game: id, set: null, color: null, finish: null, language: null })} />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={url.get('q')} onChange={(v) => url.set({ q: v })} placeholder={t('Search your cards')} />
        <SetSelect game={game} value={url.get('set')} onChange={(v) => url.set({ set: v })} />
        {gameInfo && (
          <Select
            className="w-40"
            value={url.get('finish')}
            onChange={(v) => url.set({ finish: v })}
            options={[{ value: '', label: t('All finishes') }, ...gameInfo.finishes.map((f) => ({ value: f.code, label: finishName(gameInfo, f.code) }))]}
          />
        )}
        <Select
          className="w-44"
          value={url.get('condition')}
          onChange={(v) => url.set({ condition: v })}
          options={[{ value: '', label: t('All conditions') }, ...CONDITIONS.map((c) => ({ value: c.code, label: `${c.code} - ${t(c.name)}` }))]}
        />
        {gameInfo && (
          <Select
            className="w-40"
            value={url.get('language')}
            onChange={(v) => url.set({ language: v })}
            options={[{ value: '', label: t('All languages') }, ...gameInfo.languages.map((l) => ({ value: l, label: languageName(l) }))]}
          />
        )}
        <Select
          className="w-44"
          value={filters.sort}
          onChange={(v) => url.set({ sort: v })}
          options={Object.entries(SORTS).map(([k, v]) => ({ value: k, label: t(v) }))}
        />
        <ColorFilter game={gameInfo} value={url.getAll('color')} onChange={(v) => url.set({ color: v })} />
      </div>

      {items.isError && <div className="alert alert-error">{items.error.message}</div>}
      {items.data && items.data.total === 0 && (
        <div className="hero rounded-box bg-base-200 py-12">
          <div className="hero-content text-center">
            <div>
              <p className="text-lg">{t('No cards here yet.')}</p>
              <Link to="/catalog" className="btn btn-primary mt-4">{t('Browse the catalog')}</Link>
            </div>
          </div>
        </div>
      )}
      {items.data && items.data.total > 0 && (
        <>
          <div className="text-sm text-base-content/60">
            {t('{{count}} items', { count: items.data.total })} · {t('this page {{value}}', { value: pageValue })}
          </div>
          <div className={`overflow-x-auto rounded-box border border-base-300 ${items.isPlaceholderData ? 'opacity-60' : ''}`}>
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>{t('Card')}</th>
                  <th>{t('Version')}</th>
                  <th className="text-center">{t('Qty')}</th>
                  <th className="text-right">{t('Unit')}</th>
                  <th className="text-right">{t('Total')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.data.items.map((item) => {
                  const g = games.find((x) => x.id === item.game_id)
                  return (
                    <tr key={item.id} className="hover:bg-base-200">
                      <td>
                        <Link to={`/cards/${item.card_id}/${item.printing_id}`} className="link-hover font-medium">{item.name}</Link>
                        <div className="text-xs text-base-content/60">
                          {item.set.code} {item.collector_number} · {item.set.name}
                          {!game && ` · ${g?.name ?? item.game_id}`}
                        </div>
                        {item.notes && <div className="text-xs italic text-base-content/60">{item.notes}</div>}
                      </td>
                      <td className="whitespace-nowrap text-xs">
                        <div className="flex items-center gap-1">
                          <FinishBadge game={g} finish={item.finish} />
                          <ConditionBadge condition={item.condition} />
                          <LangFlag lang={item.language} />
                        </div>
                      </td>
                      <td>
                        <div className="join justify-center">
                          <button className="btn join-item btn-xs" disabled={adjust.isPending || item.quantity === 0} onClick={() => step(item, -1)} aria-label={t('Remove one')}>−</button>
                          <span className="join-item btn btn-xs pointer-events-none w-10">{item.quantity}</span>
                          <button className="btn join-item btn-xs" disabled={adjust.isPending} onClick={() => step(item, 1)} aria-label={t('Add one')}>+</button>
                        </div>
                      </td>
                      <td className="text-right whitespace-nowrap">
                        {formatMoney(item.unit_price, item.currency)}
                        {item.manual_price !== null && <span className="badge badge-xs badge-info ml-1" title={t('Manual price')}>M</span>}
                      </td>
                      <td className="text-right font-medium whitespace-nowrap">{formatMoney(item.total, item.currency)}</td>
                      <td>
                        <button className="btn btn-ghost btn-xs" onClick={() => setEditing(item)}>{t('Edit')}</button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={items.data.total} onChange={url.goToPage} />
          </div>
        </>
      )}
      {items.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
      <ItemDialog item={editing} onClose={() => setEditing(null)} />
    </div>
  )
}
