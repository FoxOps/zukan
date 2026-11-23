import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGame, useGames, useMe } from '../api/queries'
import { useCardStock } from '../components/CardStock'
import { ActiveFilters, FilterColumn, FilterField, FilterGroup, FiltersButton } from '../components/FilterColumn'
import { AdvancedFilters, ColorFilter, GameTabs, RegionPicker, SearchInput, SetSelect, type ColorMode } from '../components/Filters'
import { EmptyState, PageHeader } from '../components/Page'
import { Select } from '../components/Select'
import { Pagination } from '../components/Pagination'
import { useFilterSheet } from '../lib/filterSheet'
import { useUrlState } from '../lib/hooks'
import { ViewToggle } from '../components/ViewToggle'
import { useView } from '../lib/views'
import { CATALOG_VIEWS } from './catalog/views'

const PAGE_SIZE = 48

export default function Catalog() {
  const { t } = useTranslation()
  const url = useUrlState()
  const me = useMe()
  const sheet = useFilterSheet()
  const stock = useCardStock()
  // Games chosen in the settings; a single one is selected right away.
  const only = me.data?.catalog_games ?? null
  const game = url.get('game') || (only?.length === 1 ? only[0] : '')
  const q = url.get('q')
  const setId = url.get('set')
  const colors = url.getAll('color')
  const attrs = url.getAll('attr')
  const colorMode = (url.get('colormode') === 'exact' ? 'exact' : 'include') as ColorMode
  // Sorting is offered inside one set: by name or by collector number.
  const sort = setId ? url.get('sort') : ''
  const [sortBy, order] = sort ? (sort.split('_') as ['name' | 'number', 'asc' | 'desc']) : [undefined, undefined]
  const gameInfo = useGame(game)
  const { data: games = [] } = useGames()
  const [view, chooseView] = useView(CATALOG_VIEWS, 'tcg.catalogView')
  const View = view.component

  const cards = useQuery({
    queryKey: ['cards', game, q, setId, colors, colorMode, attrs, sort, url.page],
    meta: { inlineError: true },
    queryFn: ({ signal }) =>
      call(
        api.GET('/api/cards', {
          signal,
          params: {
            query: {
              game: game || undefined,
              q: q || undefined,
              set_id: setId ? Number(setId) : undefined,
              color: colors.length ? colors : undefined,
              color_mode: colors.length ? colorMode : undefined,
              sort: sortBy,
              order,
              attr: game && attrs.length ? attrs : undefined,
              page: url.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  })

  const active = (setId ? 1 : 0) + (colors.length ? 1 : 0) + attrs.length + (sort ? 1 : 0)
  const clearFilters = () => url.set({ set: null, color: null, colormode: null, attr: null, sort: null })
  const gameName = games.find((g) => g.id === game)?.name

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow={t('Your card encyclopedia')}
        title={t('Catalog')}
        subtitle={t('Find cards across your games, languages and printings.')}
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        {only?.length === 0 ? (
          <div className="alert">{t('No game is selected in your settings.')}</div>
        ) : (
          <GameTabs regions={false} value={game} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, attr: null, sort: null })} />
        )}
        <Link to="/settings" className="link link-hover text-sm text-base-content/70">{t('Choose the games shown')}</Link>
      </div>
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start">
        <FilterColumn sheet={sheet} onReset={clearFilters} canReset={active > 0}>
          {!gameInfo && <p className="text-sm text-base-content/70">{t('Choose a game to filter by set, color and attributes.')}</p>}
          <RegionPicker label value={game} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, attr: null, sort: null })} />
          {gameInfo && (
            <>
              <FilterField label={t('Set')}>
                <SetSelect className="w-full" game={game} value={setId} onChange={(v) => url.set({ set: v, sort: v ? sort : null })} />
              </FilterField>
              {setId && (
                <FilterField label={t('Sort by')}>
                  <Select
                    className="w-full"
                    value={sort}
                    onChange={(v) => url.set({ sort: v || null })}
                    aria-label={t('Sort by')}
                    options={[
                      { value: '', label: t('Best match') },
                      { value: 'number_asc', label: t('Card number (ascending)') },
                      { value: 'number_desc', label: t('Card number (descending)') },
                      { value: 'name_asc', label: t('Name (A to Z)') },
                      { value: 'name_desc', label: t('Name (Z to A)') },
                    ]}
                  />
                </FilterField>
              )}
              {gameInfo.colors.length > 0 && (
                <FilterField label={t('Colors')}>
                  <ColorFilter
                    game={gameInfo}
                    value={colors}
                    onChange={(v) => url.set({ color: v })}
                    mode={colorMode}
                    onModeChange={(m) => url.set({ colormode: m === 'exact' ? m : null })}
                  />
                </FilterField>
              )}
              {gameInfo.filters.length > 0 && (
                <FilterGroup label={t('Game attributes')} active={attrs.length > 0}>
                  <AdvancedFilters game={gameInfo} value={attrs} onChange={(v) => url.set({ attr: v })} />
                </FilterGroup>
              )}
            </>
          )}
        </FilterColumn>

        <section className="flex min-w-0 flex-1 flex-col gap-4" aria-label={t('Results')}>
          <div className="flex gap-2">
            <SearchInput className="w-full flex-1" value={q} onChange={(v) => url.set({ q: v })} placeholder={t('Name in any language')} />
            <FiltersButton sheet={sheet} active={active} />
          </div>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3 text-sm text-base-content/70" aria-live="polite">
              {cards.data && (
                <span>
                  <b className="text-base-content">{t('{{count}} cards', { count: cards.data.total })}</b>
                  {gameName && ` · ${gameName}`}
                </span>
              )}
              {cards.isPlaceholderData && <span className="loading loading-spinner loading-xs" aria-label={t('Loading')} />}
            </div>
            <ViewToggle views={CATALOG_VIEWS} value={view.id} onChange={chooseView} />
          </div>
          <ActiveFilters count={active} onClear={clearFilters} />
          {cards.isError && <div className="alert alert-error">{cards.error.message}</div>}
          {cards.data && cards.data.total === 0 && (
            <EmptyState
              title={t('No matching cards.')}
              actions={
                active > 0 || q ? (
                  <button className="btn btn-primary" onClick={() => url.set({ q: null, set: null, color: null, colormode: null, attr: null, sort: null })}>
                    {t('Clear filters')}
                  </button>
                ) : undefined
              }
            >
              {t('Try another name or clear your filters.')}
            </EmptyState>
          )}
          {cards.data && cards.data.total > 0 && (
            <>
              <View cards={cards.data.items} games={games} showGame={!game} add={stock.add} adding={stock.loading} />
              <div className="flex justify-center">
                <Pagination page={url.page} pageSize={PAGE_SIZE} total={cards.data.total} onChange={url.goToPage} />
              </div>
            </>
          )}
          {cards.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
        </section>
      </div>
      {stock.dialog}
    </div>
  )
}
