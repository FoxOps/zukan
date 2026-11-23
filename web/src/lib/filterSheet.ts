import { useCallback, useRef, useState } from 'react'

/** Open state of the filters on phones and tablets (a sheet over the page); on large
 * screens the column is always there. The filters themselves live in the URL, so they stay
 * as they are when the sheet closes and opens again. */
export function useFilterSheet() {
  const [open, setOpen] = useState(false)
  const opener = useRef<HTMLElement | null>(null)
  const show = useCallback((e: React.MouseEvent<HTMLElement>) => {
    opener.current = e.currentTarget
    setOpen(true)
  }, [])
  // Focus back on the button that opened the sheet.
  const close = useCallback(() => {
    setOpen(false)
    opener.current?.focus()
  }, [])
  return { open, show, close }
}
export type FilterSheet = ReturnType<typeof useFilterSheet>
