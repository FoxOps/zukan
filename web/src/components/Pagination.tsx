type Props = { page: number; pageSize: number; total: number; onChange: (page: number) => void }

export function Pagination({ page, pageSize, total, onChange }: Props) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="join">
      <button className="join-item btn btn-sm" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        «
      </button>
      <span className="join-item btn btn-sm pointer-events-none">
        {page} / {pages}
      </span>
      <button className="join-item btn btn-sm" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        »
      </button>
    </div>
  )
}
