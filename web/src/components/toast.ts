import { createContext, useContext } from 'react'

export type Kind = 'success' | 'error' | 'info'
export type ToastAction = { label: string; run: () => void }
export type ToastFn = (text: string, kind?: Kind, action?: ToastAction) => void

export const ToastContext = createContext<ToastFn>(() => {})

export function useToast() {
  return useContext(ToastContext)
}

// Errors raised outside components (failed background queries), shown as toasts.
const errorListeners = new Set<(text: string) => void>()

export function showError(text: string) {
  errorListeners.forEach((listener) => listener(text))
}

export function onShowError(listener: (text: string) => void): () => void {
  errorListeners.add(listener)
  return () => {
    errorListeners.delete(listener)
  }
}
