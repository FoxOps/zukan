import { useTranslation } from 'react-i18next'
import type { Schemas } from '../api/client'

type Trend = Schemas['TrendOut']
type Trends = Schemas['TrendsOut']

const SHAPES = {
  up: { line: '5.5 15.5 10 11 13 13.5 18.5 8.5', head: '14.5 8.5 18.5 8.5 18.5 12.5', color: 'text-success' },
  down: { line: '5.5 8.5 10 13 13 10.5 18.5 15.5', head: '14.5 15.5 18.5 15.5 18.5 11.5', color: 'text-error' },
  flat: { line: '5.5 12 18.5 12', head: '15 8.5 18.5 12 15 15.5', color: 'text-base-content/50' },
} as const

/** Market chart arrow in a circle: rising, stable or falling price. */
export function TrendIcon({ trend, label }: { trend: Trend | null | undefined; label: string }) {
  const { t } = useTranslation()
  if (!trend) {
    return (
      <span className="inline-flex h-5 w-5 items-center justify-center text-base-content/30" title={`${label}: ${t('no price history yet')}`}>
        –
      </span>
    )
  }
  const shape = SHAPES[trend.direction]
  const percent = `${trend.change > 0 ? '+' : ''}${(trend.change * 100).toFixed(1)} %`
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-5 w-5 fill-none stroke-current ${shape.color}`}
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={`${label}: ${percent}`}
    >
      <title>{`${label}: ${percent}`}</title>
      <circle cx="12" cy="12" r="10.5" strokeWidth={1.5} />
      <polyline points={shape.line} />
      <polyline points={shape.head} />
    </svg>
  )
}

const PERIODS = [
  ['d1', '24h'],
  ['d7', '7d'],
  ['d30', '30d'],
] as const

/** "24h ↗ | 7d → | 30d ↘" */
export function TrendIcons({ trends }: { trends: Trends | undefined }) {
  const { t } = useTranslation()
  return (
    <div className="flex items-center justify-center gap-1 text-xs text-base-content/60">
      {PERIODS.map(([key, label], i) => (
        <span key={key} className="flex items-center gap-0.5">
          {i > 0 && <span className="mr-0.5 text-base-content/20">|</span>}
          {t(label)}
          <TrendIcon trend={trends?.[key]} label={t(label)} />
        </span>
      ))}
    </div>
  )
}
