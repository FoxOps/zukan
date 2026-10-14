import { useSearchParams } from 'react-router'

/** Filters kept in the URL so pages can be bookmarked and survive reloads. */
export function useUrlState() {
  const [params, setParams] = useSearchParams()
  const get = (key: string) => params.get(key) ?? ''
  const getAll = (key: string) => params.getAll(key)
  const set = (changes: Record<string, string | string[] | number | null>, resetPage = true) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key)
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v))
      else if (value !== null && value !== '') next.set(key, String(value))
    }
    if (resetPage && !('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }
  // A new page starts at its top, like a page load would.
  const goToPage = (page: number) => {
    set({ page }, false)
    window.scrollTo({ top: 0 })
  }
  return { get, getAll, set, goToPage, page: Number(params.get('page')) || 1 }
}
