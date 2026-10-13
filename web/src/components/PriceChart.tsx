import { useTranslation } from 'react-i18next'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { formatDate, formatMoney } from '../lib/format'

const COLORS = ['var(--color-primary)', 'var(--color-secondary)', 'var(--color-accent)', 'var(--color-info)']

type Point = { date: string; [series: string]: number | string | null }

/** Lines per series (finishes), or a single `value` series. */
export function PriceChart({ data, series, height = 240 }: { data: Point[]; series: string[]; height?: number }) {
  const { t } = useTranslation()
  if (data.length === 0) {
    return <div className="py-8 text-center text-sm text-base-content/60">{t('No price data yet')}</div>
  }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="currentColor" strokeOpacity={0.1} />
        <XAxis dataKey="date" tickFormatter={formatDate} fontSize={12} minTickGap={32} />
        <YAxis tickFormatter={(v) => formatMoney(v)} fontSize={12} width={72} />
        <Tooltip
          labelFormatter={(d) => formatDate(String(d))}
          formatter={(v) => formatMoney(v as number)}
          contentStyle={{ background: 'var(--color-base-200)', border: 'none', borderRadius: 8 }}
        />
        {series.length > 1 && <Legend />}
        {series.map((s, i) => (
          <Line key={s} type="monotone" dataKey={s} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={data.length < 3} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}
