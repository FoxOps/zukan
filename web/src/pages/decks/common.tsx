import { useTranslation } from 'react-i18next'
import { useDeckFormats, type Deck } from '../../api/queries'

/** Cards in a deck against its format's size ("98 / 100"), and its rule errors. */
export function DeckCount({ deck }: { deck: Deck }) {
  const { t } = useTranslation()
  const { data: games = [] } = useDeckFormats()
  const format = games.flatMap((g) => g.formats).find((f) => f.id === deck.format)
  return (
    <span className="flex flex-wrap items-center gap-1 text-xs">
      <span className="badge badge-sm badge-ghost">
        {format ? `${deck.card_count} / ${format.size}${format.exact_size ? '' : '+'}` : deck.card_count}
      </span>
      {deck.sideboard_count > 0 && <span className="badge badge-sm badge-ghost">{t('Sideboard {{n}}', { n: deck.sideboard_count })}</span>}
      {deck.errors > 0 ? (
        <span className="badge badge-sm badge-warning">{t('{{count}} issues', { count: deck.errors })}</span>
      ) : (
        <span className="badge badge-sm badge-success">{t('Format rules met')}</span>
      )}
    </span>
  )
}
