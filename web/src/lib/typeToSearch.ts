import { useEffect } from 'react'

/** Marks the page's search field: typing anywhere on the page goes there. */
export const TYPE_TO_SEARCH = { 'data-type-to-search': '' }
/** The catalog search of the top bar: used only on pages without their own search field. */
export const TYPE_TO_SEARCH_GLOBAL = { 'data-type-to-search': 'global' }

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
      const fields = Array.from(document.querySelectorAll<HTMLInputElement>('input[data-type-to-search]')).filter(
        (input) => input.offsetParent !== null && !input.disabled,
      )
      const field = fields.find((input) => input.dataset.typeToSearch !== 'global') ?? fields[0]
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
