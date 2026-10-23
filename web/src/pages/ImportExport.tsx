import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { upload, type Schemas } from '../api/client'
import { useGames } from '../api/queries'
import { useInvalidateStock } from '../api/stock'
import { useToast } from '../components/toast'
import { Select } from '../components/Select'

type Report = Schemas['ImportOut']

const EXAMPLE = `game,set_code,collector_number,name,language,finish,condition,quantity,manual_price,notes
mtg,DOM,168,Llanowar Elves,fr,foil,NM,2,,
sorcery,001,abundance-b,Abundance,en,standard,EX,1,4.50,binder 2`

export default function ImportExport() {
  const { t } = useTranslation()
  const { data: games = [] } = useGames()
  const toast = useToast()
  const invalidate = useInvalidateStock()
  const [exportGame, setExportGame] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<'add' | 'set'>('add')
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)

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
          <div className="flex flex-wrap gap-2">
            <Select
              className="w-56"
              value={exportGame}
              onChange={setExportGame}
              options={[{ value: '', label: t('All games') }, ...games.map((g) => ({ value: g.id, label: g.name }))]}
            />
            <a
              className="btn btn-primary"
              href={`/api/collection/export.csv${exportGame ? `?game=${exportGame}` : ''}`}
              download
            >
              {t('Download CSV')}
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
          </div>
          <input
            type="file"
            accept=".csv,text/csv,text/plain"
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
                <div role="alert" className="alert alert-success alert-soft">
                  {report.dry_run
                    ? t('{{count}} rows are valid. Ready to import.', { count: report.rows })
                    : t('{{imported}} of {{rows}} rows imported.', { imported: report.imported, rows: report.rows })}
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
                          <th>{t('Line')}</th>
                          <th>{t('Problem')}</th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.errors.map((e, i) => (
                          <tr key={i}>
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
