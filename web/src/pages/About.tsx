import { useTranslation } from 'react-i18next'
import { useAndroidRelease, useGames, useHealth } from '../api/queries'
import { Mascot } from '../components/Logo'
import { PageHeader, Panel } from '../components/Page'

/** What Zukan is, where its data comes from, and the notices publishers ask fan tools to show. */
export default function About() {
  const { t, i18n } = useTranslation()
  const health = useHealth()
  const games = useGames()
  const android = useAndroidRelease()

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div className="flex items-end gap-4">
        <Mascot className="h-16 w-16 object-contain" />
        <PageHeader eyebrow={t('Your card encyclopedia')} title={t('About Zukan')} subtitle={health.data?.version && `v${health.data.version}`} />
      </div>

      <Panel>
      <div className="prose max-w-none text-base-content">
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
      </Panel>

      {android.data && (
        <Panel>
          <div className="flex flex-row flex-wrap items-center gap-4">
            <div className="flex-1">
              <h2 className="text-xl">{t('Android app')}</h2>
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
              <a href={android.data.notes_url} target="_blank" rel="noreferrer" className="btn min-h-11">{t('Release notes')}</a>
              <a href={android.data.url} className="btn btn-primary min-h-11">{t('Download APK')}</a>
            </div>
          </div>
        </Panel>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-2xl">{t('Trademarks and card data')}</h2>
        {games.isPending && <span className="loading loading-spinner" />}
        {games.data?.map((g) => (
          <Panel key={g.id} as="div" title={g.name}>
              {/* Publishers' own wording, in English. */}
              {g.legal_notice && <p lang="en" className="text-sm text-base-content/70">{g.legal_notice}</p>}
          </Panel>
        ))}
      </section>
    </div>
  )
}
