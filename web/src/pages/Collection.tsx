import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame, useGames } from '../api/queries'
import { useAdjust } from '../api/stock'
import { ColorFilter, GameTabs, SearchInput, SetSelect } from '../components/Filters'
import { ItemDialog } from '../components/ItemDialog'
import { Pagination } from '../components/Pagination'
import { Select } from '../components/Select'
import { CONDITIONS, finishName, formatMoney, languageName } from '../lib/format'
import { useUrlState } from '../lib/hooks'
import { COLLECTION_VIEWS } from './collection/views'

type Item = Schemas['ItemOut']
const VIEW_KEY = 'tcg.collectionView'

function savedView(): string | null {
  try {
    return localStorage.getItem(VIEW_KEY)
  } catch {
    return null
  }
}
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
  // View in the URL, else the last one used on this browser, else the first.
  const view = COLLECTION_VIEWS.find((v) => v.id === (url.get('view') || savedView())) ?? COLLECTION_VIEWS[0]
  const View = view.component
  const chooseView = (id: string) => {
    try {
      localStorage.setItem(VIEW_KEY, id)
    } catch {
      // Storage refused: the URL still keeps it.
    }
    url.set({ view: id }, false)
  }
  const filters = {
    game: game || undefined,
    q: url.get('q') || undefined,
    set_id: url.get('set') ? Number(url.get('set')) : undefined,
    color: url.getAll('color').length ? url.getAll('color') : undefined,
    color_mode: url.getAll('color').length && url.get('colormode') === 'exact' ? ('exact' as const) : undefined,
    finish: url.get('finish') || undefined,
    condition: (url.get('condition') || undefined) as Item['condition'] | undefined,
    language: url.get('language') || undefined,
    sort: (url.get('sort') || 'name') as keyof typeof SORTS,
  }

  const items = useQuery({
    queryKey: ['collection', filters, url.page],
    meta: { inlineError: true },
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
      <GameTabs value={game} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, finish: null, language: null })} />
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
        <ColorFilter
          game={gameInfo}
          value={url.getAll('color')}
          onChange={(v) => url.set({ color: v })}
          mode={url.get('colormode') === 'exact' ? 'exact' : 'include'}
          onModeChange={(m) => url.set({ colormode: m === 'exact' ? m : null })}
        />
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
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3 text-sm text-base-content/60">
              {t('{{count}} items', { count: items.data.total })} · {t('this page {{value}}', { value: pageValue })}
              {items.isPlaceholderData && <span className="loading loading-spinner loading-xs" aria-label={t('Loading')} />}
            </div>
            <div className="join" role="group" aria-label={t('View')}>
              {COLLECTION_VIEWS.map((v) => (
                <button
                  key={v.id}
                  className={`btn join-item btn-sm ${v.id === view.id ? 'btn-active' : ''}`}
                  aria-pressed={v.id === view.id}
                  onClick={() => chooseView(v.id)}
                >
                  {v.icon}
                  {t(v.label)}
                </button>
              ))}
            </div>
          </div>
          <View items={items.data.items} games={games} showGame={!game} busy={adjust.isPending} step={step} edit={setEditing} />
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
