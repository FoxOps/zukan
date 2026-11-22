import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { gameGroups, gameLabel, useDeckFormats, useDecks, useMe, useShownGames, type Game } from '../api/queries'
import { HiddenGamesNote } from '../components/HiddenGames'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { formatDate } from '../lib/format'
import { DeckCount } from './decks/common'
import { useFormatName } from './decks/formats'

type Body = Schemas['DeckIn']

/** New deck: a name, the game (each shown game decks support) and one of its formats. */
function CreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const navigate = useNavigate()
  const { data: gameFormats = [] } = useDeckFormats(open)
  const { shown: games } = useShownGames()
  const [name, setName] = useState('')
  const [chosenGame, setGameId] = useState<string | null>(null)
  const [chosenFormat, setFormat] = useState<string | null>(null)
  // Shown games of this server that decks can be built for: Magic first when shown.
  const deckGames = gameFormats.filter((g) => games.some((x) => x.id === g.game_id))
  const gameId = chosenGame ?? (deckGames.find((g) => g.game_id === 'mtg') ?? deckGames[0])?.game_id ?? ''
  const formats = gameFormats.find((g) => g.game_id === gameId)?.formats ?? []
  const format = chosenFormat ?? (gameId === 'mtg' ? 'commander' : formats[0]?.id) ?? ''
  const chooseGame = (id: string) => {
    setGameId(id)
    setFormat(gameFormats.find((g) => g.game_id === id)?.formats[0]?.id ?? '')
  }

  const create = useMutation({
    mutationFn: () =>
      call(api.POST('/api/decks', { body: { name: name.trim(), game_id: gameId as Body['game_id'], format: format as Body['format'] } })),
    onSuccess: async (detail) => {
      await client.invalidateQueries({ queryKey: ['decks'] })
      onClose()
      setName('')
      navigate(`/decks/${detail.deck.id}`)
    },
    onError: (e) => toast(e.message, 'error'),
  })

  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <form
          className="modal-box animate-in fade-in zoom-in-95 duration-200"
          onSubmit={(e) => {
            e.preventDefault()
            if (name.trim()) create.mutate()
          }}
        >
          <h3 className="text-lg font-bold">{t('New deck')}</h3>
          <div className="mt-4 flex flex-col gap-3">
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Name')}</span>
              <input className="input w-full" value={name} maxLength={100} autoFocus onChange={(e) => setName(e.target.value)} />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="fieldset py-0">
                <span className="fieldset-legend">{t('Game')}</span>
                <Select
                  className="w-full"
                  value={gameId}
                  onChange={chooseGame}
                  aria-label={t('Game')}
                  options={deckGames.map((g) => ({ value: g.game_id, label: games.find((x) => x.id === g.game_id)?.name ?? g.game_id }))}
                />
              </label>
              <label className="fieldset py-0">
                <span className="fieldset-legend">{t('Format')}</span>
                <Select className="w-full" value={format} onChange={setFormat} aria-label={t('Format')} options={formats.map((f) => ({ value: f.id, label: f.name }))} />
              </label>
            </div>
          </div>
          <div className="modal-action">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              {t('Cancel')}
            </button>
            <button type="submit" className="btn btn-primary" disabled={!name.trim() || !format || create.isPending}>
              {create.isPending && <span className="loading loading-spinner loading-sm" />}
              {t('Create')}
            </button>
          </div>
        </form>
      )}
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>{t('Close')}</button>
      </form>
    </dialog>
  )
}

function GameSection({ game, label, children }: { game: Game; label: string; children: ReactNode[] }) {
  return (
    <section className="flex flex-col gap-2" aria-labelledby={`decks-${game.id}`}>
      <h2 id={`decks-${game.id}`} className="font-semibold">
        {label} <span className="font-normal text-base-content/60">({children.length})</span>
      </h2>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{children}</div>
    </section>
  )
}

/** Decks module: the user's decks, grouped by game. */
export default function DecksPage() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const enabled = !!me?.modules?.includes('decks')
  const decks = useDecks(enabled)
  const formatName = useFormatName(enabled)
  const { shown, isShown } = useShownGames()
  const [creating, setCreating] = useState(false)
  if (me && !enabled) return <Navigate to="/settings" replace />
  const all = decks.data ?? []
  const list = all.filter((d) => isShown(d.game_id))
  // One section per game, in the server's game order; decks last changed first inside.
  const sections = gameGroups(shown).flatMap((group) =>
    group.games.map((game) => ({ game, label: gameLabel(group, game, t), decks: list.filter((d) => d.game_id === game.id) })),
  ).filter((s) => s.decks.length > 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">
            {t('Decks')} <span className="badge badge-sm badge-outline align-middle">{t('Beta')}</span>
          </h1>
          <p className="text-sm text-base-content/60">{t('Build decks for your games, check format rules and set owned copies aside for each deck.')}</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
          {t('New deck')}
        </button>
      </div>
      {decks.isPending && enabled ? (
        <span className="loading loading-spinner loading-lg m-auto block" />
      ) : list.length === 0 && all.length === 0 ? (
        <div className="card bg-base-200">
          <div className="card-body items-center text-center">
            <p>{t('No deck yet. Create one, then add cards from the catalog or paste a decklist.')}</p>
            <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
              {t('New deck')}
            </button>
          </div>
        </div>
      ) : (
        <>
          {sections.map(({ game, label, decks: gameDecks }) => (
            <GameSection key={game.id} game={game} label={label}>
              {gameDecks.map((d) => (
                <Link key={d.id} to={`/decks/${d.id}`} className="card bg-base-200 transition-colors hover:bg-base-300">
                  <div className="card-body gap-2">
                    <h3 className="card-title text-base leading-tight">{d.name}</h3>
                    <div className="text-xs text-base-content/60">
                      {formatName(d.format)} · {t('Changed {{date}}', { date: formatDate(d.updated_at) })}
                    </div>
                    <DeckCount deck={d} />
                  </div>
                </Link>
              ))}
            </GameSection>
          ))}
          <HiddenGamesNote count={all.length - list.length} />
        </>
      )}
      <CreateDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
