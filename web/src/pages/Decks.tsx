import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router'
import { api, call, type Schemas } from '../api/client'
import { useDeckFormats, useDecks, useGames, useMe } from '../api/queries'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { formatDate } from '../lib/format'
import { DeckCount } from './decks/common'
import { useFormatName } from './decks/formats'

type Body = Schemas['DeckIn']

/** New deck: a name, the game (Magic, Pokémon) and one of its formats. */
function CreateDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const navigate = useNavigate()
  const { data: gameFormats = [] } = useDeckFormats(open)
  const { data: games = [] } = useGames()
  const [name, setName] = useState('')
  const [gameId, setGameId] = useState('mtg')
  const [format, setFormat] = useState('commander')
  // Games of this server that decks can be built for.
  const deckGames = gameFormats.filter((g) => games.some((x) => x.id === g.game_id))
  const formats = gameFormats.find((g) => g.game_id === gameId)?.formats ?? []
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

/** Decks module: the user's decks. */
export default function DecksPage() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const enabled = !!me?.modules?.includes('decks')
  const decks = useDecks(enabled)
  const formatName = useFormatName()
  const { data: games = [] } = useGames()
  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const [creating, setCreating] = useState(false)
  if (me && !enabled) return <Navigate to="/settings" replace />
  const list = decks.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">
            {t('Decks')} <span className="badge badge-sm badge-outline align-middle">{t('Experimental')}</span>
          </h1>
          <p className="text-sm text-base-content/60">{t('Build Magic and Pokémon decks, check format rules and set owned copies aside for each deck.')}</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
          {t('New deck')}
        </button>
      </div>
      {decks.isPending && enabled ? (
        <span className="loading loading-spinner loading-lg m-auto block" />
      ) : list.length === 0 ? (
        <div className="card bg-base-200">
          <div className="card-body items-center text-center">
            <p>{t('No deck yet. Create one, then add cards from the catalog or paste a decklist.')}</p>
            <button className="btn btn-primary btn-sm" onClick={() => setCreating(true)}>
              {t('New deck')}
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((d) => (
            <Link key={d.id} to={`/decks/${d.id}`} className="card bg-base-200 transition-colors hover:bg-base-300">
              <div className="card-body gap-2">
                <h2 className="card-title text-base leading-tight">{d.name}</h2>
                <div className="text-xs text-base-content/60">
                  {gameName(d.game_id)} · {formatName(d.format)} · {t('Changed {{date}}', { date: formatDate(d.updated_at) })}
                </div>
                <DeckCount deck={d} />
              </div>
            </Link>
          ))}
        </div>
      )}
      <CreateDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  )
}
