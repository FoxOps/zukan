import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGame, useGames, useMe } from '../api/queries'
import { AdvancedFilters, ColorFilter, GameTabs, SearchInput, SetSelect, type ColorMode } from '../components/Filters'
import { Select } from '../components/Select'
import { Pagination } from '../components/Pagination'
import { useUrlState } from '../lib/hooks'
import { ViewToggle } from '../components/ViewToggle'
import { useView } from '../lib/views'
import { CATALOG_VIEWS } from './catalog/views'

const PAGE_SIZE = 48

export default function Catalog() {
  const { t } = useTranslation()
  const url = useUrlState()
  const me = useMe()
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
    queryFn: () =>
      call(
        api.GET('/api/cards', {
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

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <h1 className="text-2xl font-bold">{t('Catalog')}</h1>
        <Link to="/settings" className="link link-hover text-sm text-base-content/60">{t('Choose the games shown')}</Link>
      </div>
      {only?.length === 0 ? (
        <div className="alert">{t('No game is selected in your settings.')}</div>
      ) : (
        <GameTabs value={game} only={only} onChange={(id) => url.set({ game: id, set: null, color: null, colormode: null, attr: null, sort: null })} />
      )}
      <SearchInput value={q} onChange={(v) => url.set({ q: v })} placeholder={t('Name in any language')} />
      {gameInfo && (
        <div className="flex flex-col gap-3 rounded-box bg-base-200 p-3">
          <div className="flex flex-wrap items-center gap-3">
            <SetSelect game={game} value={setId} onChange={(v) => url.set({ set: v, sort: v ? sort : null })} />
            {setId && (
              <label className="flex w-full items-center gap-2 sm:w-auto">
                <span className="whitespace-nowrap text-sm font-medium text-base-content/70">{t('Sort by')}</span>
                <Select
                  className="w-full sm:w-56"
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
              </label>
            )}
          </div>
          <ColorFilter
            game={gameInfo}
            value={colors}
            onChange={(v) => url.set({ color: v })}
            mode={colorMode}
            onModeChange={(m) => url.set({ colormode: m === 'exact' ? m : null })}
          />
          <AdvancedFilters game={gameInfo} value={attrs} onChange={(v) => url.set({ attr: v })} />
          {(setId || colors.length > 0 || attrs.length > 0) && (
            <button className="btn btn-ghost btn-sm self-start" onClick={() => url.set({ set: null, color: null, colormode: null, attr: null, sort: null })}>
              {t('Clear filters')}
            </button>
          )}
        </div>
      )}
      {cards.isError && <div className="alert alert-error">{cards.error.message}</div>}
      {cards.data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-3 text-sm text-base-content/60">
              {t('{{count}} cards', { count: cards.data.total })}
              {cards.isPlaceholderData && <span className="loading loading-spinner loading-xs" aria-label={t('Loading')} />}
            </div>
            <ViewToggle views={CATALOG_VIEWS} value={view.id} onChange={chooseView} />
          </div>
          <View cards={cards.data.items} games={games} showGame={!game} />
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={cards.data.total} onChange={url.goToPage} />
          </div>
        </>
      )}
      {cards.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
    </div>
  )
}
