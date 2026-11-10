import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate } from 'react-router'
import { api, call } from '../api/client'
import { gameGroups, useBinders, useGames, useMe, useSets, type Binder } from '../api/queries'
import { FinishBadge, LangFlag } from '../components/Badges'
import { Select } from '../components/Select'
import { useToast } from '../components/toast'
import { finishName, languageName } from '../lib/format'

/** Owned printings of a binder, as a bar and "owned / total (percent)". */
export function BinderProgress({ binder }: { binder: Binder }) {
  const { t } = useTranslation()
  const done = binder.total > 0 && binder.owned >= binder.total
  const percent = binder.total ? Math.floor((binder.owned / binder.total) * 100) : 0
  return (
    <div className="flex flex-col gap-1">
      <progress className={`progress w-full ${done ? 'progress-success' : 'progress-primary'}`} value={binder.owned} max={binder.total || 1} />
      <div className="flex items-center justify-between text-xs text-base-content/70">
        <span>{t('{{owned}} / {{total}} cards', { owned: binder.owned, total: binder.total })}</span>
        {done ? <span className="badge badge-success badge-sm">{t('Complete')}</span> : <span>{percent} %</span>}
      </div>
    </div>
  )
}

/** Language and finish counted by a binder ("any" when it has none). */
export function BinderFilters({ binder }: { binder: Binder }) {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const game = games.find((g) => g.id === binder.game_id)
  if (!binder.language && !binder.finish) return <span className="text-xs text-base-content/60">{t('Any language and finish')}</span>
  return (
    <span className="flex flex-wrap items-center gap-1 text-xs">
      {binder.language && (
        <span className="badge badge-sm gap-1">
          <LangFlag lang={binder.language} /> {languageName(binder.language)}
        </span>
      )}
      {binder.finish && <FinishBadge game={game} finish={binder.finish} />}
    </span>
  )
}

/** Pick a game and one of its sets (not followed yet), and optionally the language and
 * finish copies must have to count. */
function FollowDialog({ open, followed, onClose }: { open: boolean; followed: number[]; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const navigate = useNavigate()
  const { data: me } = useMe()
  const { data: allGames = [] } = useGames()
  const games = allGames.filter((g) => !me?.catalog_games || me.catalog_games.includes(g.id))
  const [gameId, setGameId] = useState('')
  const [setId, setSetId] = useState('')
  const [language, setLanguage] = useState('')
  const [finish, setFinish] = useState('')
  const game = games.find((g) => g.id === gameId)
  const { data: sets = [] } = useSets(gameId || null)
  const choices = sets.filter((s) => !followed.includes(s.id))

  const follow = useMutation({
    mutationFn: () =>
      call(api.POST('/api/binder', { body: { set_id: Number(setId), language: language || null, finish: finish || null } })),
    onSuccess: async (binder) => {
      await client.invalidateQueries({ queryKey: ['binder'] })
      onClose()
      navigate(`/binder/${binder.id}`)
    },
    onError: (e) => toast(e.message, 'error'),
  })
  const pickGame = (id: string) => {
    setGameId(id)
    setSetId('')
    setLanguage('')
    setFinish('')
  }

  return (
    <dialog className={`modal ${open ? 'modal-open' : ''}`} onClose={onClose}>
      {open && (
        <div className="modal-box animate-in fade-in zoom-in-95 duration-200">
          <h3 className="text-lg font-bold">{t('Follow a set')}</h3>
          <div className="mt-4 flex flex-col gap-3">
            <label className="fieldset py-0">
              <span className="fieldset-legend">{t('Game')}</span>
              <Select
                className="w-full"
                value={gameId}
                onChange={pickGame}
                aria-label={t('Game')}
                options={[
                  { value: '', label: t('Choose a game') },
                  ...gameGroups(games).flatMap((group) =>
                    group.games.map((g) => ({ value: g.id, label: group.games.length > 1 ? `${group.name} · ${t(g.region_label ?? g.name)}` : g.name })),
                  ),
                ]}
              />
            </label>
            {game && (
              <>
                <label className="fieldset py-0">
                  <span className="fieldset-legend">{t('Set')}</span>
                  <Select
                    className="w-full"
                    value={setId}
                    onChange={setSetId}
                    aria-label={t('Set')}
                    options={[
                      { value: '', label: t('Choose a set') },
                      ...choices.map((s) => ({
                        value: String(s.id),
                        label: `${s.code} - ${s.name}${s.exclusive_lang ? ` (${languageName(s.exclusive_lang)})` : ''}`,
                      })),
                    ]}
                  />
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label className="fieldset py-0">
                    <span className="fieldset-legend">{t('Language')}</span>
                    <Select
                      className="w-full"
                      value={language}
                      onChange={setLanguage}
                      aria-label={t('Language')}
                      options={[{ value: '', label: t('Any language') }, ...game.languages.map((l) => ({ value: l, label: languageName(l) }))]}
                    />
                  </label>
                  <label className="fieldset py-0">
                    <span className="fieldset-legend">{t('Finish')}</span>
                    <Select
                      className="w-full"
                      value={finish}
                      onChange={setFinish}
                      aria-label={t('Finish')}
                      options={[{ value: '', label: t('Any finish') }, ...game.finishes.map((f) => ({ value: f.code, label: finishName(game, f.code) }))]}
                    />
                  </label>
                </div>
                <p className="text-xs text-base-content/60">{t('Only copies in this language and finish check a card off.')}</p>
              </>
            )}
          </div>
          <div className="modal-action">
            <button className="btn btn-ghost" onClick={onClose}>
              {t('Cancel')}
            </button>
            <button className="btn btn-primary" disabled={!setId || follow.isPending} onClick={() => follow.mutate()}>
              {follow.isPending && <span className="loading loading-spinner loading-sm" />}
              {t('Follow')}
            </button>
          </div>
        </div>
      )}
      <form method="dialog" className="modal-backdrop">
        <button onClick={onClose}>{t('Close')}</button>
      </form>
    </dialog>
  )
}

/** Binder module: the sets the user follows, each with its progress. */
export default function BinderPage() {
  const { t } = useTranslation()
  const { data: me } = useMe()
  const enabled = !!me?.modules?.includes('binder')
  const binders = useBinders(enabled)
  const { data: games = [] } = useGames()
  const [following, setFollowing] = useState(false)
  if (me && !enabled) return <Navigate to="/settings" replace />
  const list = binders.data ?? []

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold">{t('Binder')}</h1>
          <p className="text-sm text-base-content/60">{t('Follow sets and check off the cards you own.')}</p>
        </div>
        <button className="btn btn-primary btn-sm" onClick={() => setFollowing(true)}>
          {t('Follow a set')}
        </button>
      </div>
      {binders.isPending && enabled ? (
        <span className="loading loading-spinner loading-lg m-auto block" />
      ) : list.length === 0 ? (
        <div className="card bg-base-200">
          <div className="card-body items-center text-center">
            <p>{t('No set followed yet. Follow one to see which of its cards you are missing.')}</p>
            <button className="btn btn-primary btn-sm" onClick={() => setFollowing(true)}>
              {t('Follow a set')}
            </button>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((b) => (
            <Link key={b.id} to={`/binder/${b.id}`} className="card bg-base-200 transition-colors hover:bg-base-300">
              <div className="card-body gap-3">
                <div className="flex items-start gap-3">
                  {b.set.icon && <img src={b.set.icon} alt="" className="h-8 w-8 object-contain" loading="lazy" />}
                  <div className="min-w-0">
                    <h2 className="card-title text-base leading-tight">{b.set.name}</h2>
                    <div className="text-xs text-base-content/60">
                      {games.find((g) => g.id === b.game_id)?.name ?? b.game_id} · {b.set.code}
                    </div>
                  </div>
                </div>
                <BinderFilters binder={b} />
                <BinderProgress binder={b} />
              </div>
            </Link>
          ))}
        </div>
      )}
      <FollowDialog open={following} followed={list.map((b) => b.set.id)} onClose={() => setFollowing(false)} />
    </div>
  )
}
