import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, useNavigate, useParams } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { useBinder, useGame, useMe } from '../../api/queries'
import { useAdjust } from '../../api/stock'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { CardImage } from '../../components/CardImage'
import { SearchInput } from '../../components/Filters'
import { RarityBadge } from '../../components/RarityBadge'
import { Select } from '../../components/Select'
import { ShownName } from '../../components/ShownName'
import { StockDialog, type StockTarget } from '../../components/StockDialog'
import { useToast } from '../../components/toast'
import { finishName, languageName, normalize } from '../../lib/format'
import { BinderFilters, BinderProgress } from '../Binder'

type Row = Schemas['BinderRowOut']
type Shown = 'all' | 'missing' | 'owned'

const SHOWN: { id: Shown; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'missing', label: 'Missing' },
  { id: 'owned', label: 'Owned' },
]

/** One followed set: every printing in collector number order, ticked when owned.
 * Ticking opens the stock dialog to add a copy; unticking removes one after a confirm. */
export default function BinderDetail() {
  const { t } = useTranslation()
  const { binderId } = useParams()
  const { data: me } = useMe()
  const query = useBinder(Number(binderId))
  const binder = query.data?.binder
  const game = useGame(binder?.game_id)
  const adjust = useAdjust()
  const toast = useToast()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [shown, setShown] = useState<Shown>('all')
  const [search, setSearch] = useState('')
  const [adding, setAdding] = useState<StockTarget | null>(null)
  const [removing, setRemoving] = useState<Row | null>(null)
  const [unfollowing, setUnfollowing] = useState(false)

  const update = useMutation({
    mutationFn: (body: Schemas['BinderUpdateIn']) =>
      call(api.PATCH('/api/binder/{binder_id}', { params: { path: { binder_id: Number(binderId) } }, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: ['binder'] }),
    onError: (e) => toast(e.message, 'error'),
  })
  const unfollow = useMutation({
    mutationFn: () => call(api.DELETE('/api/binder/{binder_id}', { params: { path: { binder_id: Number(binderId) } } })),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ['binder'] })
      navigate('/binder')
    },
    onError: (e) => toast(e.message, 'error'),
  })

  if (me && !me.modules?.includes('binder')) return <Navigate to="/settings" replace />
  if (query.isPending) return <span className="loading loading-spinner loading-lg m-auto block" />
  if (!query.data || !binder) return null

  const words = normalize(search)
  const rows = query.data.rows.filter(
    (r) =>
      (shown === 'all' || (shown === 'owned') === r.quantity > 0) &&
      (!words || normalize(`${r.collector_number ?? ''} ${r.name} ${r.translation ?? ''}`).includes(words)),
  )
  const counts = { all: query.data.rows.length, owned: binder.owned, missing: binder.total - binder.owned }
  // Some games print no collector numbers (Sorcery).
  const numbered = query.data.rows.some((r) => r.collector_number)
  const tick = (row: Row) => {
    if (row.quantity > 0) {
      setRemoving(row)
      return
    }
    setAdding({
      printingId: row.printing_id,
      title: `${[binder.set.code, row.collector_number].filter(Boolean).join(' ')} · ${row.name}`,
      finishes: row.finishes,
      languages: row.languages,
      finish: binder.finish,
      language: binder.language,
    })
  }
  const removeOne = (row: Row, item: Row['items'][number]) =>
    adjust.mutate(
      { printing_id: row.printing_id, finish: item.finish, condition: item.condition as Schemas['AdjustIn']['condition'], language: item.language, delta: -1, source: 'web' },
      { onSuccess: () => setRemoving(null) },
    )

  return (
    <div className="flex flex-col gap-4">
      <Link to="/binder" className="link-hover w-fit text-sm text-base-content/70">
        ← {t('Binder')}
      </Link>
      <div className="card bg-base-200">
        <div className="card-body gap-4 lg:flex-row lg:items-center">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            {binder.set.icon && <img src={binder.set.icon} alt="" className="h-10 w-10 object-contain" />}
            <div className="min-w-0">
              <h1 className="text-2xl font-bold leading-tight">{binder.set.name}</h1>
              <div className="text-sm text-base-content/60">
                {game?.name ?? binder.game_id} · {binder.set.code}
              </div>
              <div className="mt-1">
                <BinderFilters binder={binder} />
              </div>
            </div>
          </div>
          <div className="w-full lg:w-72">
            <BinderProgress binder={binder} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div role="tablist" className="tabs tabs-box w-fit">
          {SHOWN.map((s) => (
            <button key={s.id} role="tab" className={`tab ${shown === s.id ? 'tab-active' : ''}`} onClick={() => setShown(s.id)}>
              {t(s.label)} ({counts[s.id]})
            </button>
          ))}
        </div>
        <SearchInput value={search} onChange={setSearch} placeholder={t('Search this set')} />
        {game && (
          <>
            <Select
              className="w-40"
              value={binder.language ?? ''}
              disabled={update.isPending}
              onChange={(v) => update.mutate({ language: v || null })}
              aria-label={t('Language')}
              options={[{ value: '', label: t('Any language') }, ...game.languages.map((l) => ({ value: l, label: languageName(l) }))]}
            />
            <Select
              className="w-40"
              value={binder.finish ?? ''}
              disabled={update.isPending}
              onChange={(v) => update.mutate({ finish: v || null })}
              aria-label={t('Finish')}
              options={[{ value: '', label: t('Any finish') }, ...game.finishes.map((f) => ({ value: f.code, label: finishName(game, f.code) }))]}
            />
          </>
        )}
        <button className="btn btn-ghost btn-sm ml-auto text-error" onClick={() => setUnfollowing(true)}>
          {t('Stop following')}
        </button>
      </div>

      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table table-sm">
          <thead>
            <tr>
              <th className="w-10">
                <span className="sr-only">{t('Owned')}</span>
              </th>
              <th className="w-12" />
              {numbered && <th className="w-16">{t('Number')}</th>}
              <th>{t('Card')}</th>
              <th>{t('Rarity')}</th>
              <th className="text-right">{t('Copies')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const owned = row.quantity > 0
              const link = `/cards/${row.card_id}/${row.printing_id}`
              return (
                <tr key={row.printing_id} className={`hover:bg-base-200 ${owned ? '' : 'text-base-content/70'}`}>
                  <td>
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm checkbox-primary"
                      checked={owned}
                      onChange={() => tick(row)}
                      aria-label={owned ? t('Remove a copy of {{name}}', { name: row.name }) : t('Add {{name}}', { name: row.name })}
                    />
                  </td>
                  <td>
                    <Link to={link} className={`block w-10 ${owned ? '' : 'opacity-50 grayscale'}`} tabIndex={-1} aria-hidden>
                      <CardImage thumb src={row.image} alt={row.name} landscape={row.orientation === 'landscape'} />
                    </Link>
                  </td>
                  {numbered && <td className="whitespace-nowrap font-mono text-xs">{row.collector_number}</td>}
                  <td>
                    <Link to={link} className="link-hover font-medium">
                      <ShownName name={row.name} translation={row.translation} />
                    </Link>
                  </td>
                  <td className="text-xs">
                    <RarityBadge game={game} rarity={row.rarity} code={row.rarity_code} lang={binder.set.lang} />
                  </td>
                  <td className="text-right font-medium">{owned ? row.quantity : '—'}</td>
                </tr>
              )
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={numbered ? 6 : 5} className="py-6 text-center text-base-content/60">
                  {t('No card here.')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <StockDialog game={game} target={adding} onClose={() => setAdding(null)} />

      <dialog className={`modal ${removing ? 'modal-open' : ''}`} onClose={() => setRemoving(null)}>
        {removing && (
          <div className="modal-box animate-in fade-in zoom-in-95 duration-200">
            <h3 className="text-lg font-bold">{t('Remove a copy of {{name}}?', { name: removing.name })}</h3>
            <p className="py-2 text-sm">{t('One copy is removed from your collection.')}</p>
            <ul className="flex flex-col gap-2">
              {removing.items.map((item) => (
                <li key={item.id} className="flex items-center gap-2 rounded-box bg-base-200 px-3 py-2">
                  <FinishBadge game={game} finish={item.finish} />
                  <ConditionBadge condition={item.condition} />
                  <LangFlag lang={item.language} />
                  <span className="text-sm">× {item.quantity}</span>
                  <button className="btn btn-error btn-sm ml-auto" disabled={adjust.isPending} onClick={() => removeOne(removing, item)}>
                    {t('Remove one')}
                  </button>
                </li>
              ))}
            </ul>
            <div className="modal-action">
              <button className="btn btn-ghost" onClick={() => setRemoving(null)}>
                {t('Cancel')}
              </button>
            </div>
          </div>
        )}
        <form method="dialog" className="modal-backdrop">
          <button onClick={() => setRemoving(null)}>{t('Close')}</button>
        </form>
      </dialog>

      <dialog className={`modal ${unfollowing ? 'modal-open' : ''}`} onClose={() => setUnfollowing(false)}>
        {unfollowing && (
          <div className="modal-box">
            <h3 className="text-lg font-bold">{t('Stop following {{set}}?', { set: binder.set.name })}</h3>
            <p className="py-2 text-sm">{t('Your collection is not changed.')}</p>
            <div className="modal-action">
              <button className="btn btn-ghost" onClick={() => setUnfollowing(false)}>
                {t('Cancel')}
              </button>
              <button className="btn btn-error" disabled={unfollow.isPending} onClick={() => unfollow.mutate()}>
                {t('Stop following')}
              </button>
            </div>
          </div>
        )}
        <form method="dialog" className="modal-backdrop">
          <button onClick={() => setUnfollowing(false)}>{t('Close')}</button>
        </form>
      </dialog>
    </div>
  )
}
