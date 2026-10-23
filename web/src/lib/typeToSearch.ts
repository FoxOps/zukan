import { useEffect } from 'react'

/** Marks the page's search field: typing anywhere on the page goes there. */
export const TYPE_TO_SEARCH = { 'data-type-to-search': '' }

function typing(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

/** Typing while no field has the focus (and no dialog is open) moves it to the page's
 * search field, which then gets the typed character; "/" only moves the focus. */
export function useTypeToSearch() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return
      if (e.key.length !== 1 || e.key === ' ' || typing(e.target)) return
      if (document.querySelector('dialog[open], .modal-open')) return
      const field = Array.from(document.querySelectorAll<HTMLInputElement>('input[data-type-to-search]')).find(
        (input) => input.offsetParent !== null && !input.disabled,
      )
      if (!field) return
      field.focus()
      // The browser types the key into the field now focused; the cursor goes after
      // what is already there.
      const end = field.value.length
      field.setSelectionRange(end, end)
      if (e.key === '/') e.preventDefault()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])
}
