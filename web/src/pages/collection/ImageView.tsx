import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { CardImage } from '../../components/CardImage'
import { ShownName } from '../../components/ShownName'
import { TrendIcons } from '../../components/TrendIcon'
import { formatMoney } from '../../lib/format'
import { Stepper, UnitPrice } from './parts'
import { itemLink, type ViewProps } from './types'

/** Card pictures in a grid, like the catalog. */
export function ImageView({ items, games, showGame, busy, step, edit }: ViewProps) {
  const { t } = useTranslation()
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {items.map((item) => {
        const g = games.find((x) => x.id === item.game_id)
        return (
          <div key={item.id} className="flex flex-col gap-2">
            <Link to={itemLink(item)} className="group relative">
              <CardImage src={item.image} back={item.back_image} alt={item.name} faceClassName="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]" />
              <span className="badge badge-neutral absolute bottom-[3%] left-[3%] font-semibold shadow">×{item.quantity}</span>
            </Link>
            <div className="flex flex-col gap-1">
              <Link to={itemLink(item)} className="link-hover break-words font-medium">
                <ShownName name={item.name} translation={item.translation} />
              </Link>
              <span className="text-xs text-base-content/60">
                {item.set.code} {item.collector_number}
                {showGame && ` · ${g?.name ?? item.game_id}`}
              </span>
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
                <button className="btn btn-ghost btn-xs" onClick={() => edit(item)}>{t('Edit')}</button>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
