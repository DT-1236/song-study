import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { fetchTokens } from './api'
import type { Token } from './api'

const MAX_OPEN_TABS = 5

export type Tab = {
  documentId: number
  title: string
  lastAccessedAt: number
}

type TabsContextValue = {
  tabs: Tab[]
  openIds: Set<number>
  processingIds: Set<number>
  visitDocument: (documentId: number, title: string) => void
  ensureProcessed: (documentId: number, title: string) => Promise<Token[]>
}

const TabsContext = createContext<TabsContextValue | null>(null)

export function TabsProvider({ children }: { children: ReactNode }) {
  const [tabs, setTabs] = useState<Tab[]>([])
  const [processingIds, setProcessingIds] = useState<Set<number>>(new Set())

  const navigate = useNavigate()
  const location = useLocation()
  const currentPathnameRef = useRef(location.pathname)
  useEffect(() => {
    currentPathnameRef.current = location.pathname
  }, [location.pathname])

  // The document whose processing completion should navigate the user to it,
  // and the pathname they were on when they asked for it. If they've since
  // navigated elsewhere, or asked for a different document, this no longer
  // matches by the time processing finishes and the auto-navigate is skipped.
  const pendingAutoNavRef = useRef<{ documentId: number; pathname: string } | null>(null)
  const inFlightRef = useRef<Map<number, Promise<Token[]>>>(new Map())

  const visitDocument = useCallback((documentId: number, title: string) => {
    setTabs((prev) => {
      const now = Date.now()
      const existingIndex = prev.findIndex((tab) => tab.documentId === documentId)

      if (existingIndex !== -1) {
        const next = [...prev]
        next[existingIndex] = { ...next[existingIndex], title, lastAccessedAt: now }
        return next
      }

      const next = [...prev, { documentId, title, lastAccessedAt: now }]

      if (next.length > MAX_OPEN_TABS) {
        let lruIndex = 0
        for (let i = 1; i < next.length; i++) {
          if (next[i].lastAccessedAt < next[lruIndex].lastAccessedAt) lruIndex = i
        }
        next.splice(lruIndex, 1)
      }

      return next
    })
  }, [])

  const ensureProcessed = useCallback(
    (documentId: number, title: string): Promise<Token[]> => {
      pendingAutoNavRef.current = { documentId, pathname: currentPathnameRef.current }

      const existing = inFlightRef.current.get(documentId)
      if (existing) return existing

      setProcessingIds((prev) => new Set(prev).add(documentId))

      const promise = fetchTokens(documentId).finally(() => {
        inFlightRef.current.delete(documentId)
        setProcessingIds((prev) => {
          const next = new Set(prev)
          next.delete(documentId)
          return next
        })
        visitDocument(documentId, title)

        const pending = pendingAutoNavRef.current
        const targetPath = `/documents/${documentId}`
        if (
          pending &&
          pending.documentId === documentId &&
          pending.pathname === currentPathnameRef.current &&
          currentPathnameRef.current !== targetPath
        ) {
          navigate(targetPath)
        }
      })

      inFlightRef.current.set(documentId, promise)
      return promise
    },
    [navigate, visitDocument],
  )

  const openIds = useMemo(() => new Set(tabs.map((tab) => tab.documentId)), [tabs])

  const value = useMemo(
    () => ({ tabs, openIds, processingIds, visitDocument, ensureProcessed }),
    [tabs, openIds, processingIds, visitDocument, ensureProcessed],
  )

  return <TabsContext.Provider value={value}>{children}</TabsContext.Provider>
}

export function useTabs() {
  const ctx = useContext(TabsContext)
  if (!ctx) throw new Error('useTabs must be used within a TabsProvider')
  return ctx
}
