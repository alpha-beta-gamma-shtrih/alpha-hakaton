import { useEffect, useSyncExternalStore, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { PixelArt } from './pixel'

/* One floating AI button per screen. The application form owns it while it is open
   (its panel works with the unsaved draft); every other client page shows the global one. */
let owners = 0
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

/** Called by a page that renders its own AI dock; the global dock steps aside while it is mounted. */
export function useClaimAiDock() {
  useEffect(() => {
    owners++
    emit()
    return () => {
      owners--
      emit()
    }
  }, [])
}

export function useAiDockClaimed() {
  return useSyncExternalStore(subscribe, () => owners > 0)
}

export function AiDockShell({ open, onOpen, onClose, subtitle, children }: { open: boolean; onOpen: () => void; onClose: () => void; subtitle: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])
  return createPortal(
    <>
      {!open && (
        <button type="button" className="ai-fab" onClick={onOpen} aria-label="Открыть ИИ-помощника">
          <span className="ai-fab-ic">
            <PixelArt shape="smile" size={3} gap={1} color="var(--lime)" animate={false} />
          </span>
          <span className="ai-fab-t">
            <b>ИИ-помощник</b>
            <span>{subtitle}</span>
          </span>
        </button>
      )}
      {open && (
        <aside className="ai-drawer" role="dialog" aria-label="ИИ-помощник">
          <button type="button" className="ai-close" onClick={onClose} aria-label="Закрыть">
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 3l10 10M13 3 3 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          {children}
        </aside>
      )}
    </>,
    document.body,
  )
}
