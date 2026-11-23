import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { CardImage } from '../../components/CardImage'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { TrendIcons } from '../../components/TrendIcon'
import { Icon } from '../../components/Icon'
import { formatMoney } from '../../lib/format'
import { Stepper, UnitPrice } from './parts'
import { itemLink, type ViewProps } from './types'

/** Card pictures in a grid, like the catalog. */
export function ImageView({ items, games, showGame, busy, step, edit }: ViewProps) {
  const { t } = useTranslation()
  return (
    <ul className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
      {items.map((item) => {
        const g = games.find((x) => x.id === item.game_id)
        return (
          <li key={item.id} className="flex min-w-0 flex-col gap-2">
            <Link to={itemLink(item)} className="group relative">
              <CardImage thumb src={item.image} back={item.back_image} alt={item.name} landscape={item.orientation === 'landscape'} game={item.game_id} setCode={item.set.code} number={item.collector_number} />
              <span className="badge badge-sm absolute left-[4%] top-[3%] border-base-300 bg-base-100 font-semibold text-base-content shadow">
                <Icon name="check" className="h-3 w-3" />
                {t('{{count}} owned', { count: item.quantity })}
              </span>
            </Link>
            <div className="flex flex-col gap-1">
              <Link to={itemLink(item)} className="link-hover break-words font-display text-base font-extrabold">
                <ShownName name={item.name} translation={item.translation} />
              </Link>
              <span className="text-xs text-base-content/70">
                {item.set.code} {item.collector_number}
                {showGame && ` · ${g?.name ?? item.game_id}`}
              </span>
              <RarityBadge game={g} rarity={item.rarity} code={item.rarity_code} lang={item.language} className="text-xs text-base-content/70" />
              <div className="flex flex-wrap items-center gap-1 text-xs">
                <FinishBadge game={g} finish={item.finish} />
                <ConditionBadge condition={item.condition} />
                <LangFlag lang={item.language} />
              </div>
              <div className="flex items-center justify-between gap-2 text-sm">
                <span><UnitPrice item={item} /></span>
                <span className="font-medium">{formatMoney(item.total, item.currency)}</span>
              </div>
              <TrendIcons trends={item.trends} />
              <div className="flex items-center justify-between gap-1">
                <Stepper item={item} busy={busy} step={step} />
                <button className="btn btn-sm" onClick={() => edit(item)}>{t('Edit')}</button>
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
