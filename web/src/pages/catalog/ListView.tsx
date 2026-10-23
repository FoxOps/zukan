import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { CardImage } from '../../components/CardImage'
import { ColorBadges } from '../../components/ColorBadges'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { PriceRange } from './PriceRange'
import { cardLink, type CatalogViewProps } from './types'

/** One row per card: small picture, name, shown version, rarity, colors, prices. */
export function ListView({ cards, games, showGame }: CatalogViewProps) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto rounded-box border border-base-300">
      <table className="table table-sm">
        <thead>
          <tr>
            <th className="w-12" />
            <th>{t('Card')}</th>
            <th>{t('Version')}</th>
            <th>{t('Rarity')}</th>
            <th>{t('Colors')}</th>
            <th className="text-right">{t('Price')}</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => {
            const game = games.find((g) => g.id === card.game_id)
            return (
              <tr key={card.id} className="hover:bg-base-200">
                <td>
                  <Link to={cardLink(card)} className="block w-10" tabIndex={-1} aria-hidden>
                    <CardImage src={card.image} alt={card.name} landscape={card.orientation === 'landscape'} />
                  </Link>
                </td>
                <td>
                  <Link to={cardLink(card)} className="link-hover font-medium">
                    <ShownName name={card.name} translation={card.translation} />
                  </Link>
                  <div className="text-xs text-base-content/60">
                    {showGame && `${game?.name ?? card.game_id} · `}
                    {t('{{count}} printings', { count: card.printing_count })}
                  </div>
                </td>
                <td className="text-xs">
                  {card.set && (
                    <>
                      <div className="whitespace-nowrap">
                        {card.set.code} {card.collector_number}
                      </div>
                      <div className="text-base-content/60">{card.set.name}</div>
                    </>
                  )}
                </td>
                <td className="text-xs">
                  <RarityBadge game={game} rarity={card.rarity} code={card.rarity_code} lang={card.set?.lang} />
                </td>
                <td>
                  <ColorBadges game={game} colors={card.colors} />
                </td>
                <td className="text-right whitespace-nowrap font-medium">
                  <PriceRange card={card} />
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

