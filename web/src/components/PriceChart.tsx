import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import type { Point } from './PriceChartLines'

// The chart library is large: downloaded the first time a chart has something to draw.
const Lines = lazy(() => import('./PriceChartLines'))

/** Lines per series (finishes), or a single `value` series. */
export function PriceChart({
  data,
  series,
  height = 240,
  currency = 'EUR',
}: {
  data: Point[]
  series: string[]
  height?: number
  currency?: string
}) {
  const { t } = useTranslation()
  if (data.length === 0) {
    return <div className="py-8 text-center text-sm text-base-content/60">{t('No price data yet')}</div>
  }
  return (
    <Suspense fallback={<div style={{ height }} className="flex items-center justify-center"><span className="loading loading-spinner" /></div>}>
      <Lines data={data} series={series} height={height} currency={currency} />
    </Suspense>
  )
}
