import { useTranslation } from 'react-i18next'
import { formatMoney } from '../../lib/format'
import type { Item, ViewProps } from './types'

export function Stepper({ item, busy, step }: { item: Item; busy: boolean; step: ViewProps['step'] }) {
  const { t } = useTranslation()
  return (
    <div className="join justify-center">
      <button className="btn join-item btn-xs" disabled={busy || item.quantity === 0} onClick={() => step(item, -1)} aria-label={t('Remove one')}>−</button>
      <span className="join-item btn btn-xs pointer-events-none w-10">{item.quantity}</span>
      <button className="btn join-item btn-xs" disabled={busy} onClick={() => step(item, 1)} aria-label={t('Add one')}>+</button>
    </div>
  )
}

export function UnitPrice({ item }: { item: Item }) {
  const { t } = useTranslation()
  return (
    <>
      {formatMoney(item.unit_price, item.currency)}
      {item.manual_price !== null && <span className="badge badge-xs badge-info ml-1" title={t('Manual price')}>M</span>}
    </>
  )
}
