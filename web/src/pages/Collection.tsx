import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useGame, useGames } from '../api/queries'
import { useAdjust } from '../api/stock'
import { ActiveFilters, FilterColumn, FilterField, FiltersButton } from '../components/FilterColumn'
import { ColorFilter, GameTabs, RegionPicker, SearchInput, SetSelect } from '../components/Filters'
import { Icon } from '../components/Icon'
import { EmptyState, PageHeader } from '../components/Page'
import { useFilterSheet } from '../lib/filterSheet'
import { ItemDialog } from '../components/ItemDialog'
import { Pagination } from '../components/Pagination'
import { Select } from '../components/Select'
import { CONDITIONS, finishName, formatMoney, languageName } from '../lib/format'
import { useUrlState } from '../lib/hooks'
import { ViewToggle } from '../components/ViewToggle'
import { useView } from '../lib/views'
import { COLLECTION_VIEWS } from './collection/views'

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
  const sheet = useFilterSheet()
  const [editing, setEditing] = useState<Item | null>(null)
  const [view, chooseView] = useView(COLLECTION_VIEWS, 'tcg.collectionView')
  const View = view.component
  const filters = {
    game: game || undefined,
    q: url.get('q') || undefined,
    set_id: url.get('set') ? Number(url.get('set')) : undefined,
    color: url.getAll('color').length ? url.getAll('color') : undefined,
    color_mode: url.getAll('color').length && url.get('colormode') === 'exact' ? ('exact' as const) : undefined,
    finish: url.get('finish') || undefined,
    condition: (url.get('condition') || undefined) as Item['condition'] | undefined,
    language: url.get('language') || undefined,
    no_price: url.get('noprice') === '1' || undefined,
    sort: (url.get('sort') || 'name') as keyof typeof SORTS,
  }

  const items = useQuery({
    queryKey: ['collection', filters, url.page],
    meta: { inlineError: true },
    queryFn: ({ signal }) =>
      call(
        api.GET('/api/collection', {
          signal,
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

  const active = ['set', 'finish', 'condition', 'language', 'noprice'].filter((k) => url.get(k)).length + (url.getAll('color').length ? 1 : 0)
  const clearFilters = () => url.set({ set: null, color: null, colormode: null, finish: null, condition: null, language: null, noprice: null })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t('Your inventory')}
        title={t('Collection')}
        subtitle={t('Every printing, finish and copy in one place.')}
        action={
          <Link to="/catalog" className="btn btn-primary min-h-11 gap-2">
            <Icon name="plus" />
            {t('Add cards')}
          </Link>
        }
      />
      <GameTabs regions={false} value={game} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, finish: null, language: null })} />
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <FilterColumn sheet={sheet} onReset={clearFilters} canReset={active > 0}>
          <RegionPicker label value={game} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, finish: null, language: null })} />
          {gameInfo && (
            <FilterField label={t('Set')}>
              <SetSelect className="w-full" game={game} value={url.get('set')} onChange={(v) => url.set({ set: v })} />
            </FilterField>
          )}
          <FilterField label={t('Condition')}>
            <Select
              className="w-full"
              value={url.get('condition')}
              onChange={(v) => url.set({ condition: v })}
              aria-label={t('Condition')}
              options={[{ value: '', label: t('All conditions') }, ...CONDITIONS.map((c) => ({ value: c.code, label: `${c.code} - ${t(c.name)}` }))]}
            />
          </FilterField>
          {gameInfo && (
            <>
              <FilterField label={t('Finish')}>
                <Select
                  className="w-full"
                  value={url.get('finish')}
                  onChange={(v) => url.set({ finish: v })}
                  aria-label={t('Finish')}
                  options={[{ value: '', label: t('All finishes') }, ...gameInfo.finishes.map((f) => ({ value: f.code, label: finishName(gameInfo, f.code) }))]}
                />
              </FilterField>
              <FilterField label={t('Language')}>
                <Select
                  className="w-full"
                  value={url.get('language')}
                  onChange={(v) => url.set({ language: v })}
                  aria-label={t('Language')}
                  options={[{ value: '', label: t('All languages') }, ...gameInfo.languages.map((l) => ({ value: l, label: languageName(l) }))]}
                />
              </FilterField>
            </>
          )}
          {gameInfo && gameInfo.colors.length > 0 && (
            <FilterField label={t('Colors')}>
              <ColorFilter
                game={gameInfo}
                value={url.getAll('color')}
                onChange={(v) => url.set({ color: v })}
                mode={url.get('colormode') === 'exact' ? 'exact' : 'include'}
                onModeChange={(m) => url.set({ colormode: m === 'exact' ? m : null })}
              />
            </FilterField>
          )}
          <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm">
            <input
              type="checkbox"
              className="checkbox checkbox-sm"
              checked={filters.no_price === true}
              onChange={(e) => url.set({ noprice: e.target.checked ? '1' : null })}
            />
            {t('Without price')}
          </label>
          {!gameInfo && <p className="text-xs text-base-content/70">{t('Choose a game for set, finish, language and color filters.')}</p>}
        </FilterColumn>

        <section className="flex min-w-0 flex-1 flex-col gap-4" aria-label={t('Results')}>
          <div className="flex gap-2">
            <SearchInput className="w-full flex-1" value={url.get('q')} onChange={(v) => url.set({ q: v })} placeholder={t('Search your cards')} />
            <FiltersButton sheet={sheet} active={active} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-base-content/70" aria-live="polite">
              {items.data && (
                <span>
                  <b className="text-base-content">{t('{{count}} items', { count: items.data.total })}</b> · {t('this page {{value}}', { value: pageValue })}
                </span>
              )}
              {items.isPlaceholderData && <span className="loading loading-spinner loading-xs" aria-label={t('Loading')} />}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Select
                className="w-52"
                value={filters.sort}
                onChange={(v) => url.set({ sort: v })}
                aria-label={t('Sort by')}
                options={Object.entries(SORTS).map(([k, v]) => ({ value: k, label: t(v) }))}
              />
              <ViewToggle views={COLLECTION_VIEWS} value={view.id} onChange={chooseView} />
            </div>
          </div>
          <ActiveFilters count={active} onClear={clearFilters} />
          {items.isError && <div className="alert alert-error">{items.error.message}</div>}
          {items.data && items.data.total === 0 && (
            active > 0 || url.get('q') ? (
              <EmptyState
                title={t('No matching cards.')}
                actions={<button className="btn btn-primary" onClick={() => url.set({ q: null, set: null, color: null, colormode: null, finish: null, condition: null, language: null, noprice: null })}>{t('Clear filters')}</button>}
              >
                {t('Try another name or clear your filters.')}
              </EmptyState>
            ) : (
              <EmptyState
                title={t('No cards here yet.')}
                actions={
                  <>
                    <Link to="/catalog" className="btn btn-primary">{t('Browse the catalog')}</Link>
                    <Link to="/import" className="btn">{t('Import a collection')}</Link>
                  </>
                }
              />
            )
          )}
          {items.data && items.data.total > 0 && (
            <>
              <View items={items.data.items} games={games} showGame={!game} busy={adjust.isPending} step={step} edit={setEditing} />
              <div className="flex justify-center">
                <Pagination page={url.page} pageSize={PAGE_SIZE} total={items.data.total} onChange={url.goToPage} />
              </div>
            </>
          )}
          {items.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
        </section>
      </div>
      <ItemDialog item={editing} onClose={() => setEditing(null)} />
    </div>
  )
}
