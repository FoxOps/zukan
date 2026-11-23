import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, call, type Schemas } from '../../api/client'
import { Icon } from '../../components/Icon'

type Neighbor = Schemas['NeighborOut']

/** Previous and next card of the printing's set, in collector-number order, to page
 * through a set without going back to the catalog. The open tab is kept. */
export function SetNeighbors({ printingId, setCode, tab }: { printingId: number; setCode: string; tab: string }) {
  const { t } = useTranslation()
  const neighbors = useQuery({
    queryKey: ['printing-neighbors', printingId],
    queryFn: () => call(api.GET('/api/printings/{printing_id}/neighbors', { params: { path: { printing_id: printingId } } })),
    staleTime: 60 * 60_000,
  })
  const { previous, next } = neighbors.data ?? { previous: null, next: null }
  if (!previous && !next) return null
  const link = (n: Neighbor, rel: 'prev' | 'next') => (
    <Link
      to={`/cards/${n.card_id}/${n.printing_id}${tab === 'printings' ? '' : `?tab=${tab}`}`}
      rel={rel}
      className={`btn btn-ghost min-h-11 max-w-[48%] gap-2 px-2 font-normal ${rel === 'next' ? 'ml-auto text-right' : ''}`}
      aria-label={`${rel === 'prev' ? t('Previous card in the set') : t('Next card in the set')}: ${setCode} ${n.collector_number ?? ''} ${n.name}`}
    >
      {rel === 'prev' && <Icon name="chevron" className="h-4 w-4 rotate-180" />}
      <span className="min-w-0 truncate">
        <span className="tabular-nums text-base-content/70">
          {setCode} {n.collector_number}
        </span>{' '}
        <span className="font-semibold">{n.name}</span>
      </span>
      {rel === 'next' && <Icon name="chevron" className="h-4 w-4" />}
    </Link>
  )
  return (
    <nav aria-label={t('Cards of the set')} className="flex items-center gap-2 border-y border-base-300 py-1">
      {previous && link(previous, 'prev')}
      {next && link(next, 'next')}
    </nav>
  )
}
