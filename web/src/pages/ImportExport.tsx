import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { upload, type Schemas } from '../api/client'
import { useMe, useShownGames } from '../api/queries'
import { useInvalidateStock } from '../api/stock'
import { useToast } from '../components/toast'
import { Select } from '../components/Select'

type Report = Schemas['ImportOut']

const EXAMPLE = `game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
mtg,DOM,168,Llanowar Elves,fr,foil,NM,2,,
sorcery,001,abundance-b,Abundance,en,standard,EX,1,4.50,binder 2`

type Part = 'binder' | 'decks'

export default function ImportExport() {
  const { t } = useTranslation()
  const partLabel = (part: Part) => (part === 'binder' ? t('Followed sets (Binder)') : t('Decks, their cards and allocated copies'))
  // Files of an export bundle (`services.export_bundle`).
  const fileLabel = (name: string) =>
    ({
      'cards.csv': t('Cards'),
      'binder_sets.csv': t('Followed sets'),
      'decks.csv': t('Decks'),
      'deck_cards.csv': t('Deck cards'),
      'deck_allocations.csv': t('Allocated copies'),
    })[name] ?? name
  const { games, shown } = useShownGames()
  const { data: me } = useMe()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const [exportGame, setExportGame] = useState('')
  // Parts of the modules the user has on.
  const extraParts = (['binder', 'decks'] as Part[]).filter((p) => me?.modules?.includes(p))
  const [parts, setParts] = useState<Part[]>(['binder', 'decks'])
  const chosen = ['cards', ...extraParts.filter((p) => parts.includes(p))]
  const query = new URLSearchParams(chosen.map((p) => ['parts', p]))
  if (exportGame) query.set('game', exportGame)
  const exportUrl = `/api/collection/export?${query}`
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<'add' | 'set'>('add')
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const inBundle = !!report?.errors.some((e) => e.file)

  const run = async (dryRun: boolean) => {
    if (!file) return
    setBusy(true)
    try {
      const result = await upload<Report>(`/api/collection/import?mode=${mode}&dry_run=${dryRun}`, file)
      setReport(result)
      if (!dryRun && result.errors.length === 0) {
        toast(t('{{count}} rows imported', { count: result.imported }))
        await invalidate()
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-2xl font-bold">{t('Import / export')}</h1>

      <div className="card bg-base-200">
        <div className="card-body">
          <h2 className="card-title">{t('Export')}</h2>
          <p className="text-sm">{t('Download your collection as CSV (spreadsheet-friendly, re-importable).')}</p>
          {extraParts.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-sm text-base-content/60">
                {t('With followed sets or decks, the download is a zip holding one CSV per part, which imports back here.')}
              </p>
              <div className="flex flex-wrap gap-x-6">
                <label className="label cursor-pointer gap-2 text-base-content">
                  <input type="checkbox" className="checkbox checkbox-sm" checked disabled />
                  {t('Cards')}
                </label>
                {extraParts.map((part) => (
                  <label key={part} className="label cursor-pointer gap-2 text-base-content">
                    <input
                      type="checkbox"
                      className="checkbox checkbox-sm"
                      checked={parts.includes(part)}
                      onChange={(e) => setParts(e.target.checked ? [...parts, part] : parts.filter((p) => p !== part))}
                    />
                    {partLabel(part)}
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            <Select
              className="w-56"
              value={exportGame}
              onChange={setExportGame}
              options={[{ value: '', label: t('All games') }, ...shown.map((g) => ({ value: g.id, label: g.name }))]}
            />
            <a className="btn btn-primary" href={exportUrl} download>
              {chosen.length > 1 ? t('Download zip') : t('Download CSV')}
            </a>
          </div>
        </div>
      </div>

      <div className="card bg-base-200">
        <div className="card-body gap-4">
          <h2 className="card-title">{t('Import')}</h2>
          <div className="prose prose-sm max-w-none">
            <p>
              {t('One row per item.')} <code>collector_number</code>{' '}
              {t('is the printed number, or the printing id for games without numbers (Sorcery, e.g.')}{' '}
              <code>abundance-b</code>). {t('Commas, semicolons or tabs work. If any row is invalid, nothing is imported.')}
            </p>
            <p>
              {t('Values of the game column:')}{' '}
              {games.map((g, i) => (
                <span key={g.id}>
                  {i > 0 && ', '}
                  <code>{g.id}</code> ({g.name})
                </span>
              ))}
            </p>
            <pre className="text-xs">{EXAMPLE}</pre>
            <p>
              {t('A zip exported here brings back followed sets and decks too. Decks of the same game and name get the cards added, or replaced with the second option.')}
            </p>
          </div>
          <input
            type="file"
            accept=".csv,.zip,text/csv,text/plain,application/zip"
            className="file-input w-full max-w-md"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setReport(null)
            }}
          />
          <div className="flex flex-wrap gap-4">
            <label className="label cursor-pointer gap-2">
              <input type="radio" className="radio radio-sm" checked={mode === 'add'} onChange={() => setMode('add')} />
              {t('Add quantities to my collection')}
            </label>
            <label className="label cursor-pointer gap-2">
              <input type="radio" className="radio radio-sm" checked={mode === 'set'} onChange={() => setMode('set')} />
              {t('Replace quantities of listed items')}
            </label>
          </div>
          <div className="flex gap-2">
            <button className="btn" disabled={!file || busy} onClick={() => run(true)}>
              {t('Check file')}
            </button>
            <button className="btn btn-primary" disabled={!file || busy} onClick={() => run(false)}>
              {busy && <span className="loading loading-spinner loading-sm" />}
              {t('Import')}
            </button>
          </div>

          {report && (
            <div className="animate-in fade-in duration-300">
              {report.errors.length === 0 ? (
                <div role="alert" className="alert alert-success alert-soft flex-col items-start gap-1">
                  <span>
                    {report.dry_run
                      ? t('{{count}} rows are valid. Ready to import.', { count: report.rows })
                      : t('{{imported}} of {{rows}} rows imported.', { imported: report.imported, rows: report.rows })}
                  </span>
                  {Object.keys(report.counts ?? {}).length > 0 && (
                    <ul className="text-sm">
                      {Object.entries(report.counts ?? {}).map(([name, count]) => (
                        <li key={name}>
                          {fileLabel(name)}: {count}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ) : (
                <>
                  <div role="alert" className="alert alert-error alert-soft">
                    {t('{{count}} problems found in {{rows}} rows.', { count: report.errors.length, rows: report.rows })}{' '}
                    {t('Nothing was imported.')}
                  </div>
                  <div className="mt-2 max-h-80 overflow-auto">
                    <table className="table table-xs">
                      <thead>
                        <tr>
                          {inBundle && <th>{t('File')}</th>}
                          <th>{t('Line')}</th>
                          <th>{t('Problem')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.errors.map((e, i) => (
                          <tr key={i}>
                            {inBundle && <td>{e.file ? fileLabel(e.file) : ''}</td>}
                            <td>{e.line}</td>
                            <td>{e.message}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
