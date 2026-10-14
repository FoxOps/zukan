import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router'
import { api, call } from '../../api/client'
import { useGames, useMe } from '../../api/queries'
import { Pagination } from '../../components/Pagination'
import { formatDate } from '../../lib/format'
import { useUrlState } from '../../lib/hooks'

const PAGE_SIZE = 50
// Secondary catalog sources by id.
const SOURCES: Record<string, string> = { mtgjson: 'MTGJSON', pokemontcg: 'Pokémon TCG API' }

/** Where secondary catalog sources disagree with the primary one, whose values are kept. */
export default function Checks() {
  const { t } = useTranslation()
  const me = useMe()
  const url = useUrlState()
  const { data: games = [] } = useGames()
  const game = url.get('game')
  const source = url.get('source')
  const field = url.get('field')
  const admin = me.data?.role === 'admin'
  const checks = useQuery({
    queryKey: ['discrepancies', game, source, field, url.page],
    queryFn: () =>
      call(
        api.GET('/api/admin/discrepancies', {
          params: {
            query: {
              game: game || undefined,
              source: source || undefined,
              field: field || undefined,
              page: url.page,
              page_size: PAGE_SIZE,
            },
          },
        }),
      ),
    enabled: admin,
    placeholderData: keepPreviousData,
  })
  if (!admin) return <Navigate to="/" replace />

  const gameName = (id: string) => games.find((g) => g.id === id)?.name ?? id
  const filtered = !!(game || source || field)

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Data checks')}</h1>
      <p className="text-sm text-base-content/70">
        {t('After each catalog refresh, second sources are compared with the main one. They fill missing data; where they disagree, the main source is kept and the difference is listed here.')}
      </p>

      <div className="overflow-x-auto rounded-box border border-base-300">
        <table className="table table-sm">
          <thead>
            <tr>
              <th>{t('Game')}</th>
              <th>{t('Source')}</th>
              <th>{t('Field')}</th>
              <th className="text-right">{t('Differences')}</th>
            </tr>
          </thead>
          <tbody>
            {checks.data?.counts.length === 0 && (
              <tr>
                <td colSpan={4} className="text-base-content/60">{t('No difference found.')}</td>
              </tr>
            )}
            {checks.data?.counts.map((c) => {
              const active = c.game_id === game && c.source === source && c.field === field
              return (
                <tr
                  key={`${c.game_id}-${c.source}-${c.field}`}
                  className={`cursor-pointer hover:bg-base-200 ${active ? 'bg-base-200 font-semibold' : ''}`}
                  onClick={() => url.set(active ? { game: null, source: null, field: null } : { game: c.game_id, source: c.source, field: c.field })}
                >
                  <td>{gameName(c.game_id)}</td>
                  <td>{SOURCES[c.source] ?? c.source}</td>
                  <td>{t(c.field)}</td>
                  <td className="text-right">{c.count.toLocaleString()}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {checks.data && checks.data.total > 0 && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm text-base-content/60">{t('{{count}} differences', { count: checks.data.total })}</span>
            {filtered && (
              <button className="btn btn-ghost btn-sm" onClick={() => url.set({ game: null, source: null, field: null })}>
                {t('Show all')}
              </button>
            )}
          </div>
          <div className={`overflow-x-auto rounded-box border border-base-300 ${checks.isPlaceholderData ? 'opacity-60' : ''}`}>
            <table className="table table-sm">
              <thead>
                <tr>
                  <th>{t('Set')}</th>
                  <th>{t('Card')}</th>
                  <th>{t('Field')}</th>
                  <th>{t('Kept (main source)')}</th>
                  <th>{t('Second source')}</th>
                  <th>{t('Since')}</th>
                </tr>
              </thead>
              <tbody>
                {checks.data.items.map((d) => (
                  <tr key={d.id}>
                    <td className="whitespace-nowrap">
                      <span className="font-mono text-xs">{d.set_code}</span> {d.set_name}
                    </td>
                    <td>
                      {d.card_id ? (
                        <Link className="link link-hover" to={`/cards/${d.card_id}`}>
                          {d.card_name} <span className="text-base-content/60">#{d.collector_number}</span>
                        </Link>
                      ) : (
                        <span className="text-base-content/60">{t('(set)')}</span>
                      )}
                    </td>
                    <td>{t(d.field)}</td>
                    <td>{d.primary_value}</td>
                    <td className="text-warning">{d.secondary_value}</td>
                    <td className="whitespace-nowrap">{formatDate(d.first_seen)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex justify-center">
            <Pagination page={url.page} pageSize={PAGE_SIZE} total={checks.data.total} onChange={url.goToPage} />
          </div>
        </div>
      )}
    </div>
  )
}
