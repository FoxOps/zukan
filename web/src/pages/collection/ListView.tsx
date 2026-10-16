import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { TrendIcons } from '../../components/TrendIcon'
import { formatMoney } from '../../lib/format'
import { Stepper, UnitPrice } from './parts'
import { itemLink, type ViewProps } from './types'

/** Table without pictures (default). */
export function ListView({ items, games, showGame, busy, step, edit }: ViewProps) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto rounded-box border border-base-300">
      <table className="table table-sm">
        <thead>
          <tr>
            <th>{t('Card')}</th>
            <th>{t('Version')}</th>
            <th className="text-center">{t('Qty')}</th>
            <th className="text-center">{t('Trend')}</th>
            <th className="text-right">{t('Unit')}</th>
            <th className="text-right">{t('Total')}</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const g = games.find((x) => x.id === item.game_id)
            return (
              <tr key={item.id} className="hover:bg-base-200">
                <td>
                  <Link to={itemLink(item)} className="link-hover font-medium">
                    <ShownName name={item.name} translation={item.translation} />
                  </Link>
                  <div className="text-xs text-base-content/60">
                    {item.set.code} {item.collector_number} · {item.set.name}
                    {showGame && ` · ${g?.name ?? item.game_id}`}
                  </div>
                  <RarityBadge game={g} rarity={item.rarity} code={item.rarity_code} className="text-xs text-base-content/70" />
                  {item.notes && <div className="text-xs italic text-base-content/60">{item.notes}</div>}
                </td>
                <td className="whitespace-nowrap text-xs">
                  <div className="flex items-center gap-1">
                    <FinishBadge game={g} finish={item.finish} />
                    <ConditionBadge condition={item.condition} />
                    <LangFlag lang={item.language} />
                  </div>
                </td>
                <td>
                  <Stepper item={item} busy={busy} step={step} />
                </td>
                <td className="whitespace-nowrap">
                  <TrendIcons trends={item.trends} />
                </td>
                <td className="text-right whitespace-nowrap">
                  <UnitPrice item={item} />
                </td>
                <td className="text-right font-medium whitespace-nowrap">{formatMoney(item.total, item.currency)}</td>
                <td>
                  <button className="btn btn-ghost btn-xs" onClick={() => edit(item)}>{t('Edit')}</button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
