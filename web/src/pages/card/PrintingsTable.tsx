import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import type { Game } from '../../api/queries'
import { ConditionBadge, FinishBadge, LangFlag } from '../../components/Badges'
import { RarityBadge } from '../../components/RarityBadge'
import { SetIcon } from '../../components/SetIcon'
import { finishName, formatDate, formatMoney } from '../../lib/format'
import { regionNumbers, type PrintingOut } from './printings'

type Props = {
  cardId: number
  gameId: string
  game: Game | undefined
  printings: PrintingOut[]
  selectedId: number | undefined
  // Several price sources: each one's prices under its name.
  sourceCount: number
  sourceName: (id: string) => string
  filter: string
  goTo: (p: PrintingOut) => void
  openStock: (p: PrintingOut) => void
}

/** Every printing of the card: set, numbers, rarity, finishes, prices and market links,
 * owned copies (and the decks holding them), a stock button per printing. */
export function PrintingsTable({ cardId, gameId, game, printings, selectedId, sourceCount, sourceName, filter, goTo, openStock }: Props) {
  const { t } = useTranslation()
  return (
    <div className="overflow-x-auto rounded-2xl border border-base-300 bg-base-100" tabIndex={0} role="region" aria-label={t('Printings table, scroll for more columns')}>
      <table className="table table-sm">
        <thead className="bg-neutral text-neutral-content">
          <tr>
            <th>{t('Set')}</th>
            <th>#</th>
            <th>{t('Rarity')}</th>
            <th>{t('Finishes')}</th>
            <th>{t('Price')}</th>
            <th>{t('Owned')}</th>
            <th><span className="sr-only">{t('Add / remove copies')}</span></th>
          </tr>
        </thead>
        <tbody>
          {printings.length === 0 && (
            <tr>
              <td colSpan={7} className="py-6 text-center text-base-content/70">{t('No set matches “{{q}}”.', { q: filter })}</td>
            </tr>
          )}
          {printings.map((p) => (
            <tr
              key={p.id}
              className={`cursor-pointer hover:bg-base-200 ${p.id === selectedId ? 'bg-base-200 outline-2 -outline-offset-2 outline-primary' : p.owned.length ? 'bg-success/5' : ''}`}
              aria-current={p.id === selectedId ? 'page' : undefined}
              onClick={() => goTo(p)}
            >
              <td className={p.owned.length ? 'border-l-4 border-success' : 'border-l-4 border-transparent'}>
                <div className="flex items-center gap-1.5 font-medium">
                  {p.set.icon && (
                    <SetIcon src={p.set.icon} game={gameId} className={`h-4 w-4 ${gameId === 'mtg' ? '' : 'dark:rounded-sm dark:bg-white/85 dark:p-px'}`} />
                  )}
                  <Link
                    to={`/cards/${cardId}/${p.id}`}
                    className="link-hover"
                    onClick={(e) => {
                      e.preventDefault()
                      e.stopPropagation()
                      goTo(p)
                    }}
                  >
                    {p.set.name}
                  </Link>
                  {p.id === selectedId && <span className="badge badge-primary badge-xs">{t('This page')}</span>}
                </div>
                <div className="text-xs text-base-content/70">
                  {p.set.code} · {formatDate(p.set.release_date)}
                  {p.set.exclusive_lang && (
                    <>
                      {' · '}
                      <LangFlag lang={p.set.exclusive_lang} className="h-3" />
                    </>
                  )}
                </div>
              </td>
              <td>
                {p.collector_number}
                {Object.entries(regionNumbers(p)).map(([lang, number]) => (
                  <div key={lang} className="flex items-center gap-1 text-xs text-base-content/70">
                    <LangFlag lang={lang} className="h-3" />
                    {number}
                  </div>
                ))}
              </td>
              <td><RarityBadge game={game} rarity={p.rarity} code={p.rarity_code} lang={p.set.lang} /></td>
              <td>
                <div className="flex flex-wrap gap-1">
                  {p.finishes.map((f) => <FinishBadge key={f} game={game} finish={f} />)}
                </div>
              </td>
              <td className="whitespace-nowrap">
                {p.prices.length === 0 && '—'}
                {p.prices.map((price, i) => (
                  <div key={`${price.source}-${price.finish}`} className="text-xs">
                    {/* Each source's prices under its name. */}
                    {sourceCount > 1 && (i === 0 || p.prices[i - 1].source !== price.source) && (
                      <div className={`font-semibold text-base-content/70 ${i > 0 ? 'mt-1' : ''}`}>{sourceName(price.source)}</div>
                    )}
                    <span className="text-base-content/70">{finishName(game, price.finish)}</span>{' '}
                    <span className="font-medium tabular-nums" title={t('Trend price')}>{formatMoney(price.trend, price.currency)}</span>
                    {price.low !== null && (
                      <span className="text-base-content/70" title={t('Lowest offer')}>
                        {' '}
                        ({t('from {{price}}', { price: formatMoney(price.low, price.currency) })})
                      </span>
                    )}
                  </div>
                ))}
                <div className="flex flex-wrap gap-x-2">
                  {/* Only web pages: never javascript: or other schemes from data. */}
                  {p.links.filter((l) => /^https?:\/\//.test(l.url)).map((l) => (
                    <a
                      key={l.source}
                      className="link link-secondary text-xs"
                      href={l.url}
                      target="_blank"
                      rel="noreferrer noopener"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {l.name} ↗
                    </a>
                  ))}
                </div>
              </td>
              <td>
                {p.owned.map((o) => (
                  <div key={o.item_id} className="py-0.5 text-xs">
                    <div className="flex items-center gap-1 whitespace-nowrap">
                      <span className="font-semibold">{o.quantity}×</span>
                      <FinishBadge game={game} finish={o.finish} size="badge-xs" />
                      <ConditionBadge condition={o.condition} size="badge-xs" />
                      <LangFlag lang={o.language} className="h-3" />
                    </div>
                    {/* Copies set aside for decks (Decks module): where to find them. */}
                    {(o.decks ?? []).length > 0 && (
                      <div className="flex flex-wrap items-center gap-1 pl-4 pt-0.5">
                        {o.decks.map((d) => (
                          <Link
                            key={d.deck_id}
                            to={`/decks/${d.deck_id}`}
                            className="badge badge-xs badge-outline badge-secondary"
                            title={t('Allocated to the deck {{name}}', { name: d.name })}
                            onClick={(e) => e.stopPropagation()}
                          >
                            {t('{{n}} in {{name}}', { n: d.quantity, name: d.name })}
                          </Link>
                        ))}
                        {(() => {
                          const free = o.quantity - o.decks.reduce((n, d) => n + d.quantity, 0)
                          return free > 0 && <span className="text-base-content/70">{t('{{n}} free', { n: free })}</span>
                        })()}
                      </div>
                    )}
                  </div>
                ))}
              </td>
              <td>
                <button
                  className="btn btn-sm"
                  aria-label={`${t('Add / remove copies')}: ${p.set.code} ${p.collector_number ?? ''}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    openStock(p)
                  }}
                >
                  {t('Adjust')}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
