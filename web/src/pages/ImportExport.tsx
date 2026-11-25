import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { upload, type Schemas } from '../api/client'
import { useMe, useShownGames } from '../api/queries'
import { useInvalidateStock } from '../api/stock'
import { useToast } from '../components/toast'
import { Select } from '../components/Select'
import { Icon } from '../components/Icon'
import { Eyebrow, PageHeader, Panel } from '../components/Page'
import { useImportErrorText } from './importErrors'

type Report = Schemas['ImportOut']

const EXAMPLE = `game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
mtg,DOM,168,Llanowar Elves,fr,foil,NM,2,,
sorcery,001,abundance-b,Abundance,en,standard,EX,1,4.50,binder 2`

type Part = 'binder' | 'decks'

export default function ImportExport() {
  const { t } = useTranslation()
  const errorText = useImportErrorText()
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
    <div className="flex flex-col gap-6">
      <PageHeader eyebrow={t('Your workspace')} title={t('Import / export')} subtitle={t('Move your cards, followed sets and decks in and out of Zukan.')} />
      <div className="grid items-start gap-5 lg:grid-cols-2">
      <Panel bodyClassName="flex flex-col gap-4">
          <div>
            <Eyebrow>01 · {t('Import')}</Eyebrow>
            <h2 className="mt-2 text-xl">{t('Bring your collection')}</h2>
            <p className="mt-1 text-sm text-base-content/70">{t('A CSV or a Zukan zip. Check the file before importing: if any row is invalid, nothing is imported.')}</p>
          </div>
                    <input
            type="file"
            accept=".csv,.zip,text/csv,text/plain,application/zip"
            aria-label={t('Collection file')}
            className="file-input w-full"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null)
              setReport(null)
            }}
          />
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">{t('Import mode')}</legend>
            <label className="label cursor-pointer gap-2 whitespace-normal text-base-content">
              <input type="radio" className="radio radio-sm" checked={mode === 'add'} onChange={() => setMode('add')} />
              {t('Add quantities to my collection')}
            </label>
            <label className="label cursor-pointer gap-2 whitespace-normal text-base-content">
              <input type="radio" className="radio radio-sm" checked={mode === 'set'} onChange={() => setMode('set')} />
              {t('Replace quantities of listed items')}
            </label>
          </fieldset>
          <div className="flex gap-2">
            <button className="btn min-h-11" disabled={!file || busy} onClick={() => run(true)}>
              {t('Check file')}
            </button>
            <button className="btn btn-primary min-h-11" disabled={!file || busy} onClick={() => run(false)}>
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
                    {t('Problems found: {{problems}} · Rows checked: {{rows}}.', { problems: report.errors.length, rows: report.rows })}{' '}
                    {t('Nothing was imported.')}
                  </div>
                  <div className="mt-2 max-h-80 overflow-auto rounded-xl border border-base-300" tabIndex={0} role="region" aria-label={t('Problems')}>
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
                            <td>{errorText(e)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
          <details className="rounded-xl border border-base-300 px-4 py-2">
            <summary className="min-h-9 cursor-pointer content-center text-sm font-semibold">{t('CSV format and examples')}</summary>
<div className="prose prose-sm max-w-none text-base-content">
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
          </details>
      </Panel>
      <Panel bodyClassName="flex flex-col gap-4">
          <div>
            <Eyebrow>02 · {t('Export')}</Eyebrow>
            <h2 className="mt-2 text-xl">{t('Take your data with you')}</h2>
            <p className="mt-1 text-sm text-base-content/70">{t('Download your collection as CSV (spreadsheet-friendly, re-importable).')}</p>
          </div>
          {extraParts.length > 0 && (
            <div className="flex flex-col gap-1">
              <p className="text-sm text-base-content/70">
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
              aria-label={t('Game')}
              value={exportGame}
              onChange={setExportGame}
              options={[{ value: '', label: t('All games') }, ...shown.map((g) => ({ value: g.id, label: g.name }))]}
            />
            <a className="btn btn-primary min-h-11 gap-2" href={exportUrl} download>
              <Icon name="download" />
              {chosen.length > 1 ? t('Download zip') : t('Download CSV')}
            </a>
          </div>
      </Panel>

      </div>
    </div>
  )
}
