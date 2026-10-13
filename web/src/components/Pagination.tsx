import { useState } from 'react'
import { useTranslation } from 'react-i18next'

type Props = { page: number; pageSize: number; total: number; onChange: (page: number) => void }

/** Pages around the current one, plus first and last: 1 … 4 5 [6] 7 8 … 20. */
function pageWindow(page: number, pages: number, around = 2): (number | null)[] {
  const shown = new Set([1, pages])
  for (let p = page - around; p <= page + around; p++) if (p >= 1 && p <= pages) shown.add(p)
  const sorted = [...shown].sort((a, b) => a - b)
  return sorted.flatMap((p, i) => (i > 0 && p - sorted[i - 1] > 1 ? [null, p] : [p]))
}

export function Pagination({ page, pageSize, total, onChange }: Props) {
  const { t } = useTranslation()
  const [jump, setJump] = useState('')
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  const go = (p: number) => onChange(Math.min(pages, Math.max(1, p)))
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      <div className="join">
        <button className="join-item btn btn-sm" disabled={page <= 1} onClick={() => go(page - 1)} aria-label={t('Previous page')}>
          «
        </button>
        {pageWindow(page, pages).map((p, i) =>
          p === null ? (
            <span key={`gap-${i}`} className="join-item btn btn-sm btn-disabled px-2">
              …
            </span>
          ) : (
            <button
              key={p}
              className={`join-item btn btn-sm ${p === page ? 'btn-active btn-primary' : ''}`}
              aria-current={p === page ? 'page' : undefined}
              onClick={() => go(p)}
            >
              {p}
            </button>
          ),
        )}
        <button className="join-item btn btn-sm" disabled={page >= pages} onClick={() => go(page + 1)} aria-label={t('Next page')}>
          »
        </button>
      </div>
      <form
        className="join"
        onSubmit={(e) => {
          e.preventDefault()
          const p = Number(jump)
          if (p) go(p)
          setJump('')
        }}
      >
        <input
          type="number"
          min={1}
          max={pages}
          className="join-item input input-sm w-20"
          placeholder={`/ ${pages}`}
          aria-label={t('Go to page')}
          value={jump}
          onChange={(e) => setJump(e.target.value)}
        />
        <button className="join-item btn btn-sm" disabled={!jump}>
          {t('Go')}
        </button>
      </form>
    </div>
  )
}
