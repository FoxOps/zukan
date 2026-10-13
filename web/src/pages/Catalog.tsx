import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api, call } from '../api/client'
import { useGame, useGames } from '../api/queries'
import { CardImage } from '../components/CardImage'
import { ColorBadges } from '../components/ColorBadges'
import { ColorFilter, GameTabs, SearchInput, SetSelect } from '../components/Filters'
import { Pagination } from '../components/Pagination'
import { useUrlState } from '../lib/hooks'

const PAGE_SIZE = 48

export default function Catalog() {
  const url = useUrlState()
  const game = url.get('game')
  const q = url.get('q')
  const setId = url.get('set')
  const colors = url.getAll('color')
  const gameInfo = useGame(game)
  const { data: games = [] } = useGames()

  const cards = useQuery({
    queryKey: ['cards', game, q, setId, colors, url.page],
    queryFn: () =>
      call(
        api.GET('/api/cards', {
          params: {
            query: {
              game: game || undefined,
              q: q || undefined,
              set_id: setId ? Number(setId) : undefined,
              color: colors.length ? colors : undefined,
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
      <h1 className="text-2xl font-bold">Catalog</h1>
      <GameTabs value={game} onChange={(id) => url.set({ game: id, set: null, color: null })} />
      <div className="flex flex-wrap items-center gap-3">
        <SearchInput value={q} onChange={(v) => url.set({ q: v })} placeholder="Name in any language" />
        <SetSelect game={game} value={setId} onChange={(v) => url.set({ set: v })} />
        <ColorFilter game={gameInfo} value={colors} onChange={(v) => url.set({ color: v })} />
      </div>
      {cards.isError && <div className="alert alert-error">{cards.error.message}</div>}
      {cards.data && (
        <>
          <div className="text-sm text-base-content/60">{cards.data.total.toLocaleString()} card{cards.data.total === 1 ? '' : 's'}</div>
          <div className={`grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 ${cards.isPlaceholderData ? 'opacity-60' : ''}`}>
            {cards.data.items.map((card) => (
              <Link
                key={card.id}
                to={`/cards/${card.id}`}
                className="group flex flex-col gap-2 animate-in fade-in duration-300"
              >
                <CardImage src={card.image} alt={card.name} className="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]" />
                <div className="flex flex-col gap-1">
                  <span className="truncate font-medium group-hover:text-primary">{card.name}</span>
                  <span className="text-xs text-base-content/60">
                    {!game && `${games.find((g) => g.id === card.game_id)?.name ?? card.game_id} · `}
                    {card.printing_count} printing{card.printing_count > 1 ? 's' : ''}
                  </span>
                  <ColorBadges game={games.find((g) => g.id === card.game_id)} colors={card.colors} />
                </div>
              </Link>
            ))}
          </div>
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={cards.data.total} onChange={(p) => url.set({ page: p }, false)} />
          </div>
        </>
      )}
      {cards.isPending && <span className="loading loading-dots loading-lg mx-auto" />}
    </div>
  )
}
