import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { CardImage } from '../../components/CardImage'
import { ColorBadges } from '../../components/ColorBadges'
import { RarityBadge } from '../../components/RarityBadge'
import { ShownName } from '../../components/ShownName'
import { PriceRange } from './PriceRange'
import { cardLink, type CatalogViewProps } from './types'

/** One row per card: small picture, name, shown version, rarity, colors, prices. */
export function ListView({ cards, games, showGame, add, adding }: CatalogViewProps) {
  const { t } = useTranslation()
  return (
    // Scrolls on its own when narrow, so the page never does.
    <div className="overflow-x-auto rounded-2xl border border-base-300 bg-base-100" tabIndex={0} role="region" aria-label={t('Catalog table, scroll for more columns')}>
      <table className="table">
        <thead className="bg-neutral text-neutral-content">
          <tr>
            <th className="w-12" />
            <th>{t('Card')}</th>
            <th>{t('Version')}</th>
            <th>{t('Rarity')}</th>
            <th>{t('Colors')}</th>
            <th className="text-right">{t('Price')}</th>
            <th className="text-right">{t('Versions')}</th>
            <th><span className="sr-only">{t('Collection')}</span></th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => {
            const game = games.find((g) => g.id === card.game_id)
            return (
              <tr key={card.id} className="hover:bg-base-200">
                <td>
                  <Link to={cardLink(card)} className="block w-10" tabIndex={-1} aria-hidden>
                    <CardImage thumb="small" src={card.image} alt={card.name} landscape={card.orientation === 'landscape'} />
                  </Link>
                </td>
                <td className="min-w-40">
                  <Link to={cardLink(card)} className="link-hover font-semibold">
                    <ShownName name={card.name} translation={card.translation} />
                  </Link>
                  {showGame && <div className="text-xs text-base-content/70">{game?.name ?? card.game_id}</div>}
                </td>
                <td className="text-xs">
                  {card.set && (
                    <>
                      <div className="whitespace-nowrap">
                        {card.set.code} {card.collector_number}
                      </div>
                      <div className="text-base-content/70">{card.set.name}</div>
                    </>
                  )}
                </td>
                <td className="text-xs">
                  <RarityBadge game={game} rarity={card.rarity} code={card.rarity_code} lang={card.set?.lang} />
                </td>
                <td>
                  <ColorBadges game={game} colors={card.colors} />
                </td>
                <td className="whitespace-nowrap text-right font-medium">
                  <PriceRange card={card} />
                </td>
                <td className="text-right tabular-nums">{card.printing_count}</td>
                <td className="text-right">
                  <button type="button" className="btn btn-sm" disabled={adding === card.id} onClick={() => add(card)} aria-label={`${t('Add copies')}: ${card.name}`}>
                    {adding === card.id && <span className="loading loading-spinner loading-xs" />}
                    {t('Add')}
                  </button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
