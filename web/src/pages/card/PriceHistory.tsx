import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { api, call } from '../../api/client'
import { PriceChart } from '../../components/PriceChart'
import type { PrintingOut } from './printings'

export function PriceHistory({
  printing,
  finish,
  finishLabel,
  source,
}: {
  printing: PrintingOut
  // Only this finish's prices (all finishes when null).
  finish: string | null
  finishLabel: (f: string) => string
  source: { id: string; currency: string } | undefined
}) {
  const history = useQuery({
    queryKey: ['prices', printing.id],
    queryFn: () => call(api.GET('/api/printings/{printing_id}/prices', { params: { path: { printing_id: printing.id } } })),
  })
  const { data, series } = useMemo(() => {
    const byDate = new Map<string, Record<string, number | string | null>>()
    const names = new Set<string>()
    for (const point of history.data ?? []) {
      if (point.source !== source?.id || (finish !== null && point.finish !== finish)) continue
      const name = finishLabel(point.finish)
      names.add(name)
      const row = byDate.get(point.date) ?? { date: point.date }
      row[name] = point.trend === null ? null : Number(point.trend)
      byDate.set(point.date, row)
    }
    return { data: [...byDate.values()] as { date: string }[], series: [...names] }
  }, [history.data, finish, finishLabel, source])
  if (history.isPending) return <span className="loading loading-dots" />
  return <PriceChart data={data} series={series} currency={source?.currency} />
}
