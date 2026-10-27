import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { api, call, type Schemas } from '../../api/client'
import { Select } from '../../components/Select'
import { useToast } from '../../components/toast'
import { formatDateTime } from '../../lib/format'

type Rule = Schemas['ScheduleRule']
type Mode = Rule['mode']
type Kind = 'catalog' | 'prices' | 'images' | 'refresh'
type Draft = { timezone: string; jobs: Record<Kind, Rule> }

const KINDS: Kind[] = ['catalog', 'prices', 'images', 'refresh']
const KIND_HELP: Record<Kind, string> = {
  catalog: 'New sets and cards (large downloads)',
  prices: 'Card prices',
  images: 'Card pictures of new printings',
  refresh: 'Cards missing details, fetched again one by one',
}
const MODES: { value: Mode; label: string }[] = [
  { value: 'interval', label: 'Every few hours' },
  { value: 'daily', label: 'Every day' },
  { value: 'weekly', label: 'Some days of the week' },
  { value: 'monthly', label: 'Once a month' },
]
const HOUR_PRESETS = [6, 12, 24, 48, 168]

function timezones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  const zones = intl.supportedValuesOf?.('timeZone') ?? []
  return zones.includes('UTC') ? zones : ['UTC', ...zones]
}

function browserTimezone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/** Localized short weekday names, Monday first (index = server weekday). */
function weekdayNames(language: string): string[] {
  const format = new Intl.DateTimeFormat(language, { weekday: 'short' })
  // 2024-01-01 was a Monday.
  return Array.from({ length: 7 }, (_, i) => format.format(new Date(Date.UTC(2024, 0, 1 + i, 12))))
}

/** "6 hours", "2 days", "1 week". */
function hoursLabel(hours: number, t: TFunction): string {
  if (hours % 168 === 0) return t('{{count}} weeks', { count: hours / 168 })
  if (hours % 24 === 0) return t('{{count}} days', { count: hours / 24 })
  return t('{{count}} hours', { count: hours })
}

function RuleEditor({ rule, onChange }: { rule: Rule; onChange: (rule: Rule) => void }) {
  const { t, i18n } = useTranslation()
  const days = useMemo(() => weekdayNames(i18n.language), [i18n.language])
  const set = (changes: Partial<Rule>) => onChange({ ...rule, ...changes })
  const times = rule.times ?? ['03:00']
  const weekdays = rule.weekdays ?? [0]

  return (
    <div className="flex flex-col gap-2">
      <Select
        className="select-sm w-full max-w-xs"
        value={rule.mode ?? 'interval'}
        onChange={(v) => set({ mode: v as Mode })}
        options={MODES.map((m) => ({ value: m.value, label: t(m.label) }))}
      />

      {(rule.mode ?? 'interval') === 'interval' ? (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>{t('Every')}</span>
          <input
            type="number"
            min={1}
            max={744}
            className="input input-sm w-20"
            value={rule.every_hours ?? 24}
            onChange={(e) => set({ every_hours: Math.max(1, Math.min(744, Number(e.target.value) || 1)) })}
          />
          <span>{t('hours, counted from the last run')}</span>
          <div className="join">
            {HOUR_PRESETS.map((h) => (
              <button
                key={h}
                type="button"
                className={`btn btn-xs join-item ${rule.every_hours === h ? 'btn-primary' : ''}`}
                onClick={() => set({ every_hours: h })}
              >
                {hoursLabel(h, t)}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <>
          {rule.mode === 'weekly' && (
            <div className="flex flex-wrap gap-1" role="group" aria-label={t('Days of the week')}>
              {days.map((name, day) => {
                const on = weekdays.includes(day)
                return (
                  <button
                    key={day}
                    type="button"
                    aria-pressed={on}
                    className={`btn btn-sm min-w-12 ${on ? 'btn-primary' : 'btn-outline'}`}
                    // At least one day stays selected.
                    onClick={() =>
                      set({ weekdays: on ? (weekdays.length > 1 ? weekdays.filter((d) => d !== day) : weekdays) : [...weekdays, day].sort() })
                    }
                  >
                    {name}
                  </button>
                )
              })}
            </div>
          )}
          {rule.mode === 'monthly' && (
            <label className="flex items-center gap-2 text-sm">
              {t('On day')}
              <Select
                className="select-sm w-20"
                value={String(rule.month_day ?? 1)}
                onChange={(v) => set({ month_day: Number(v) })}
                options={Array.from({ length: 28 }, (_, i) => ({ value: String(i + 1), label: String(i + 1) }))}
              />
              <span className="text-base-content/60">{t('of each month')}</span>
            </label>
          )}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span>{t('At')}</span>
            {times.map((time, i) => (
              <span key={i} className="join">
                <input
                  type="time"
                  required
                  className="input input-sm join-item w-28"
                  value={time}
                  onChange={(e) => set({ times: times.map((x, j) => (j === i ? e.target.value : x)) })}
                />
                {times.length > 1 && (
                  <button
                    type="button"
                    className="btn btn-sm join-item"
                    aria-label={t('Remove this time')}
                    onClick={() => set({ times: times.filter((_, j) => j !== i) })}
                  >
                    ✕
                  </button>
                )}
              </span>
            ))}
            {times.length < 24 && (
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => set({ times: [...times, '12:00'] })}>
                + {t('Add a time')}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  )
}

/** When the worker refreshes data: every N hours, or at set times on chosen days. */
export function ScheduleEditor() {
  const { t } = useTranslation()
  const toast = useToast()
  const client = useQueryClient()
  const saved = useQuery({
    queryKey: ['sync-schedule'],
    queryFn: () => call(api.GET('/api/admin/sync-schedule')),
  })
  // Edits not saved yet; null shows the saved schedule.
  const [edited, setDraft] = useState<Draft | null>(null)
  const draft: Draft | null =
    edited ?? (saved.data ? { timezone: saved.data.timezone, jobs: saved.data.jobs as Record<Kind, Rule> } : null)
  const draftKey = JSON.stringify(draft)
  const changed = !!edited && !!saved.data && draftKey !== JSON.stringify({ timezone: saved.data.timezone, jobs: saved.data.jobs })

  // Next set times of the rules being edited (for the draft they were asked for).
  const [checked, setChecked] = useState<{ key: string; preview: Schemas['SyncScheduleOut'] | null; error: string | null } | null>(null)
  useEffect(() => {
    if (!changed) return
    const body = JSON.parse(draftKey) as Draft
    const timer = setTimeout(async () => {
      const { data, error } = await api.POST('/api/admin/sync-schedule/preview', { body })
      const detail = (error as { detail?: unknown } | undefined)?.detail
      const message = Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg).join(' · ') : detail ? String(detail) : t('Invalid schedule')
      setChecked({ key: draftKey, preview: data ?? null, error: data ? null : message })
    }, 300)
    return () => clearTimeout(timer)
  }, [draftKey, changed, t])
  const current = changed && checked?.key === draftKey ? checked : null
  const preview = current?.preview ?? null
  const invalid = current?.error ?? null

  const done = (data: Schemas['SyncScheduleOut'], message: string) => {
    setDraft(null)
    client.setQueryData(['sync-schedule'], data)
    toast(message)
    return client.invalidateQueries({ queryKey: ['schedule'] })
  }
  const save = useMutation({
    mutationFn: () => call(api.PUT('/api/admin/sync-schedule', { body: draft! })),
    onSuccess: (data) => done(data, t('Schedule saved')),
    onError: (e) => toast(e.message, 'error'),
  })
  const reset = useMutation({
    mutationFn: () => call(api.DELETE('/api/admin/sync-schedule')),
    onSuccess: (data) => done(data, t('Schedule back to the defaults')),
    onError: (e) => toast(e.message, 'error'),
  })
  const zones = useMemo(() => timezones().map((z) => ({ value: z, label: z.replaceAll('_', ' ') })), [])

  if (!draft || !saved.data) return <span className="loading loading-spinner" />
  const upcoming = (changed ? (preview?.upcoming ?? {}) : saved.data.upcoming) as Partial<Record<Kind, string[]>>
  const browser = browserTimezone()

  return (
    <div className="card bg-base-200">
      <form
        className="card-body gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="card-title">{t('Automatic updates')}</h2>
            <p className="text-sm text-base-content/70">
              {t('When the server refreshes the data of every game. Times already passed today are not caught up.')}
            </p>
          </div>
          {saved.data.is_default && <span className="badge badge-ghost">{t('Default schedule')}</span>}
        </div>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span>{t('Time zone')}</span>
          <Select className="select-sm w-64" value={draft.timezone} onChange={(v) => setDraft({ ...draft, timezone: v })} options={zones} />
          {draft.timezone !== browser && (
            <button type="button" className="btn btn-ghost btn-xs" onClick={() => setDraft({ ...draft, timezone: browser })}>
              {t('Use mine ({{zone}})', { zone: browser.replaceAll('_', ' ') })}
            </button>
          )}
        </div>

        <div className="divide-y divide-base-300">
          {KINDS.map((kind) => {
            const rule = draft.jobs[kind]
            const next = upcoming[kind] ?? []
            return (
              <div key={kind} className="grid gap-3 py-3 md:grid-cols-[12rem_1fr]">
                <div>
                  <div className="font-medium">{t(kind)}</div>
                  <div className="text-xs text-base-content/60">{t(KIND_HELP[kind])}</div>
                </div>
                <div className="flex flex-col gap-1">
                  <RuleEditor rule={rule} onChange={(r) => setDraft({ ...draft, jobs: { ...draft.jobs, [kind]: r } })} />
                  {next.length > 0 && (
                    <div className="text-xs text-base-content/60">
                      {t('Next: {{times}}', { times: next.map((at) => formatDateTime(at)).join(' · ') })}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {invalid && <div role="alert" className="alert alert-error alert-soft text-sm">{invalid}</div>}
        <div className="card-actions items-center">
          <button className="btn btn-primary" disabled={!changed || !!invalid || save.isPending}>
            {save.isPending && <span className="loading loading-spinner loading-sm" />}
            {t('Save schedule')}
          </button>
          {changed && (
            <button type="button" className="btn btn-ghost" onClick={() => setDraft(null)}>
              {t('Cancel changes')}
            </button>
          )}
          {!saved.data.is_default && (
            <button type="button" className="btn btn-ghost ml-auto" disabled={reset.isPending} onClick={() => reset.mutate()}>
              {t('Back to defaults')}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
