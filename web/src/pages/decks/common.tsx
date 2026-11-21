import { useTranslation } from 'react-i18next'
import { useDeckFormats, type Deck } from '../../api/queries'

/** Cards in a deck against its format's size ("98 / 100"), the other sections' cards
 * (sideboard, Extra Deck, runes...), and its rule errors. */
export function DeckCount({ deck }: { deck: Deck }) {
  const { t } = useTranslation()
  const { data: games = [] } = useDeckFormats()
  const format = games.flatMap((g) => g.formats).find((f) => f.id === deck.format)
  const counted = format?.counted ?? ['commander', 'main']
  const others = Object.entries(deck.counts).filter(([section, n]) => n > 0 && !counted.includes(section as (typeof counted)[number]))
  const name = (section: string) => format?.sections.find((s) => s.id === section)?.name ?? section
  return (
    <span className="flex flex-wrap items-center gap-1 text-xs">
      <span className="badge badge-sm badge-ghost">
        {format ? `${deck.card_count} / ${format.size}${format.exact_size ? '' : '+'}` : deck.card_count}
      </span>
      {others.map(([section, n]) => (
        <span key={section} className="badge badge-sm badge-ghost">
          {t(name(section))} {n}
        </span>
      ))}
      {deck.errors > 0 ? (
        <span className="badge badge-sm badge-warning">{t('{{count}} issues', { count: deck.errors })}</span>
      ) : (
        <span className="badge badge-sm badge-success">{t('Format rules met')}</span>
      )}
      {deck.copies > 0 && (
        <>
          <span
            className={`badge badge-sm ${deck.owned >= deck.copies ? 'badge-success' : 'badge-warning'}`}
            title={t('Copies you have for this deck: set aside for it or free in your collection (copies other decks hold do not count)')}
          >
            {t('{{owned}}/{{copies}} cards owned', { owned: deck.owned, copies: deck.copies })}
          </span>
          <span
            className={`badge badge-sm ${deck.allocated >= deck.copies ? 'badge-success' : 'badge-ghost'}`}
            title={t('Copies of your collection set aside for this deck')}
          >
            {t('{{allocated}}/{{copies}} cards in the deck', { allocated: deck.allocated, copies: deck.copies })}
          </span>
        </>
      )}
    </span>
  )
}
