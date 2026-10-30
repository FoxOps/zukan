import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { CardImage } from '../../components/CardImage'
import { ColorBadges } from '../../components/ColorBadges'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { PriceRange } from './PriceRange'
import { cardLink, type CatalogViewProps } from './types'

/** Card pictures in a grid (default). */
export function ImageView({ cards, games, showGame }: CatalogViewProps) {
  const { t } = useTranslation()
  return (
    // No dimming of the grid while loading: Chrome kept the dimmed paint of images on
    // their own layers after it was removed (grayed until hovered).
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
      {cards.map((card) => {
        const game = games.find((g) => g.id === card.game_id)
        return (
          <Link key={card.id} to={cardLink(card)} className="group flex flex-col gap-2">
            <CardImage
              thumb
              src={card.image}
              back={card.back_image}
              alt={card.name}
              landscape={card.orientation === 'landscape'}
              game={card.game_id}
              setCode={card.set?.code}
              number={card.collector_number}
              faceClassName="transition-transform group-hover:-translate-y-1 group-hover:scale-[1.02]"
            />
            <div className="flex flex-col gap-1">
              <span className="break-words font-medium group-hover:text-secondary">
                <ShownName name={card.name} translation={card.translation} />
              </span>
              <span className="text-xs text-base-content/60">
                {showGame && `${game?.name ?? card.game_id} · `}
                {t('{{count}} printings', { count: card.printing_count })}
              </span>
              <RarityBadge game={game} rarity={card.rarity} code={card.rarity_code} lang={card.set?.lang} className="text-xs text-base-content/70" />
              {card.price_min !== null && (
                <span className="text-xs font-medium">
                  <PriceRange card={card} />
                </span>
              )}
              <ColorBadges game={game} colors={card.colors} />
            </div>
          </Link>
        )
      })}
    </div>
  )
}

