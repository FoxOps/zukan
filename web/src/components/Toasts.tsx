import { useCallback, useState, type ReactNode } from 'react'
import { ToastContext, type Kind, type ToastAction, type ToastFn } from './toast'

type Toast = { id: number; text: string; kind: Kind; action?: ToastAction }

const ALERT: Record<Kind, string> = {
  success: 'alert-success',
  error: 'alert-error',
  info: 'alert-info',
}

let nextId = 1

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), [])
  const show = useCallback<ToastFn>(
    (text, kind = 'success', action) => {
      const id = nextId++
      setToasts((t) => [...t.slice(-3), { id, text, kind, action }])
      setTimeout(() => dismiss(id), action ? 8000 : 4000)
    },
    [dismiss],
  )
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toast toast-end toast-bottom z-50">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`alert ${ALERT[t.kind]} animate-in fade-in slide-in-from-bottom-4 duration-300`}
          >
            <span>{t.text}</span>
            {t.action && (
              <button
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  t.action!.run()
                  dismiss(t.id)
                }}
              >
                {t.action.label}
              </button>
            )}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
