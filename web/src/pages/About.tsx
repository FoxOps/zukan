import { useTranslation } from 'react-i18next'
import { useAndroidRelease, useGames, useHealth } from '../api/queries'
import { Mascot } from '../components/Logo'

/** What Zukan is, where its data comes from, and the notices publishers ask fan tools to show. */
export default function About() {
  const { t, i18n } = useTranslation()
  const health = useHealth()
  const games = useGames()
  const android = useAndroidRelease()

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="flex items-center gap-4">
        <Mascot className="h-20 w-20 object-contain" />
        <div>
          <h1 className="text-3xl font-bold">{t('About Zukan')}</h1>
          {health.data?.version && <div className="text-sm text-base-content/50">v{health.data.version}</div>}
        </div>
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

      {android.data && (
        <section className="card card-border bg-base-100">
          <div className="card-body flex-row flex-wrap items-center gap-4 p-4">
            <div className="flex-1">
              <h2 className="card-title">{t('Android app')}</h2>
              <p className="text-sm text-base-content/70">
                {t('Version {{version}} · {{size}} MB · {{date}}', {
                  version: android.data.version,
                  size: (android.data.size / 1_000_000).toFixed(1),
                  date: new Date(android.data.published_at).toLocaleDateString(i18n.language),
                })}
              </p>
              <p className="text-sm text-base-content/70">{t('Scan cards with the phone camera. Updates are offered by the app itself.')}</p>
            </div>
            <div className="flex gap-2">
              <a href={android.data.notes_url} target="_blank" rel="noreferrer" className="btn btn-ghost btn-sm">{t('Release notes')}</a>
              <a href={android.data.url} className="btn btn-primary btn-sm">{t('Download APK')}</a>
            </div>
          </div>
        </section>
      )}

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
