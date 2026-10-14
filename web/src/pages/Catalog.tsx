import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGame, useGames, useMe } from '../api/queries'
import { CardImage } from '../components/CardImage'
import { ColorBadges } from '../components/ColorBadges'
import { AdvancedFilters, ColorFilter, GameTabs, SearchInput, SetSelect } from '../components/Filters'
import { Pagination } from '../components/Pagination'
import { formatMoney } from '../lib/format'
import { useUrlState } from '../lib/hooks'
import { ShownName } from '../components/ShownName'

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
  const [advanced, setAdvanced] = useState(attrs.length > 0)
  const gameInfo = useGame(game)
  const { data: games = [] } = useGames()

  const cards = useQuery({
    queryKey: ['cards', game, q, setId, colors, attrs, url.page],
    queryFn: () =>
      call(
        api.GET('/api/cards', {
          params: {
            query: {
              game: game || undefined,
              q: q || undefined,
              set_id: setId ? Number(setId) : undefined,
              color: colors.length ? colors : undefined,
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
        <GameTabs value={game} only={only} onChange={(id) => url.set({ game: id, set: null, color: null, attr: null })} />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={q} onChange={(v) => url.set({ q: v })} placeholder={t('Name in any language')} />
        <SetSelect game={game} value={setId} onChange={(v) => url.set({ set: v })} />
        <ColorFilter game={gameInfo} value={colors} onChange={(v) => url.set({ color: v })} />
        {!!gameInfo?.filters.length && (
          <button className={`btn btn-sm ${advanced ? 'btn-active' : 'btn-ghost'}`} aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}>
            {t('Advanced search')}
            {attrs.length > 0 && <span className="badge badge-primary badge-sm">{attrs.length}</span>}
          </button>
        )}
      </div>
      {advanced && (
        <div className="rounded-box bg-base-200 p-3 animate-in fade-in slide-in-from-top-1 duration-150">
          <AdvancedFilters game={gameInfo} value={attrs} onChange={(v) => url.set({ attr: v })} />
        </div>
      )}
      {cards.isError && <div className="alert alert-error">{cards.error.message}</div>}
      {cards.data && (
        <>
          <div className="text-sm text-base-content/60">{t('{{count}} cards', { count: cards.data.total })}</div>
          <div className={`grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 ${cards.isPlaceholderData ? 'opacity-60' : ''}`}>
            {cards.data.items.map((card) => (
              <Link
                key={card.id}
                to={card.printing_id ? `/cards/${card.id}/${card.printing_id}` : `/cards/${card.id}`}
                className="group flex flex-col gap-2 animate-in fade-in duration-300"
              >
                <CardImage src={card.image} alt={card.name} className="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]" />
                <div className="flex flex-col gap-1">
                  <span className="break-words font-medium group-hover:text-primary">
                    <ShownName name={card.name} translation={card.translation} />
                  </span>
                  <span className="text-xs text-base-content/60">
                    {!game && `${games.find((g) => g.id === card.game_id)?.name ?? card.game_id} · `}
                    {t('{{count}} printings', { count: card.printing_count })}
                  </span>
                  {card.price_min !== null && (
                    <span className="text-xs font-medium">
                      {card.price_min === card.price_max
                        ? formatMoney(card.price_min, card.currency ?? undefined)
                        : `${formatMoney(card.price_min, card.currency ?? undefined)} - ${formatMoney(card.price_max, card.currency ?? undefined)}`}
                    </span>
                  )}
                  <ColorBadges game={games.find((g) => g.id === card.game_id)} colors={card.colors} />
                </div>
              </Link>
            ))}
          </div>
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={cards.data.total} onChange={url.goToPage} />
          </div>
        </>
      )}
      {cards.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
    </div>
  )
}
