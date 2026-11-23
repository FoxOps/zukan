import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { CardImage } from '../../components/CardImage'
import { ColorBadges } from '../../components/ColorBadges'
import { Icon } from '../../components/Icon'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { PriceRange } from './PriceRange'
import { cardLink, type CatalogViewProps } from './types'

/** Card pictures in a grid as wide as the page allows (default). */
export function ImageView({ cards, games, showGame, add, adding }: CatalogViewProps) {
  const { t } = useTranslation()
  return (
    // No dimming of the grid while loading: Chrome kept the dimmed paint of images on
    // their own layers after it was removed (grayed until hovered).
    <ul className="grid grid-cols-2 gap-x-4 gap-y-6 sm:grid-cols-[repeat(auto-fill,minmax(180px,1fr))]">
      {cards.map((card) => {
        const game = games.find((g) => g.id === card.game_id)
        return (
          <li key={card.id} className="flex min-w-0 flex-col gap-2">
            <Link to={cardLink(card)} className="group flex flex-col gap-2 rounded-2xl">
              <CardImage
                thumb
                src={card.image}
                back={card.back_image}
                alt={card.name}
                landscape={card.orientation === 'landscape'}
                game={card.game_id}
                setCode={card.set?.code}
                number={card.collector_number}
              />
              <span className="break-words font-display text-base font-extrabold group-hover:underline">
                <ShownName name={card.name} translation={card.translation} />
              </span>
            </Link>
            <div className="flex flex-col gap-0.5 text-xs text-base-content/70">
              {showGame && <span>{game?.name ?? card.game_id}</span>}
              {card.set && <span className="break-words">{card.set.name}</span>}
              <span className="flex flex-wrap items-center gap-x-1">
                {card.set && `${card.set.code} · ${card.collector_number ?? ''}`}
                <RarityBadge game={game} rarity={card.rarity} code={card.rarity_code} lang={card.set?.lang} />
              </span>
            </div>
            <ColorBadges game={game} colors={card.colors} />
            {card.price_min !== null && (
              <span className="text-sm font-semibold tabular-nums">
                <PriceRange card={card} />
              </span>
            )}
            <div className="mt-auto flex flex-wrap items-center justify-between gap-2">
              <button type="button" className="btn btn-sm h-auto min-h-9 max-w-full gap-1.5 py-1 whitespace-normal" disabled={adding === card.id} onClick={() => add(card)}>
                {adding === card.id ? <span className="loading loading-spinner loading-xs" /> : <Icon name="plus" className="h-4 w-4" />}
                {t('Add copies')}
              </button>
              <span className="text-xs text-base-content/70">{t('{{count}} printings', { count: card.printing_count })}</span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
