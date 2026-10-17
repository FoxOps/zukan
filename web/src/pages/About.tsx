import { useTranslation } from 'react-i18next'
import { useGames, useHealth } from '../api/queries'

/** What Zukan is, where its data comes from, and the notices publishers ask fan tools to show. */
export default function About() {
  const { t } = useTranslation()
  const health = useHealth()
  const games = useGames()

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div>
        <h1 className="text-3xl font-bold">{t('About Zukan')}</h1>
        {health.data?.version && <div className="text-sm text-base-content/50">v{health.data.version}</div>}
      </div>

      <div className="prose max-w-none">
        <p>
          {t('Zukan (図鑑, "illustrated encyclopedia") is a self-hosted collection manager for trading card games.')}
        </p>
        <p>
          {t('Prices come from Cardmarket and TCGplayer. Missing card details are filled from tcgcsv.com, tcg-api.eu and apitcg.com.')}
        </p>
        <p>
          {t('Card names, texts, pictures and symbols belong to their publishers. Zukan is not affiliated with any of them.')}
        </p>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold">{t('Trademarks and card data')}</h2>
        {games.isPending && <span className="loading loading-spinner" />}
        {games.data?.map((g) => (
          <div key={g.id} className="card card-border bg-base-100">
            <div className="card-body gap-1 p-4">
              <h3 className="card-title text-base">{g.name}</h3>
              {/* Publishers' own wording, in English. */}
              {g.legal_notice && <p lang="en" className="text-sm text-base-content/70">{g.legal_notice}</p>}
            </div>
          </div>
        ))}
      </section>
    </div>
  )
}
