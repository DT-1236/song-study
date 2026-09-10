import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

const MAX_OPEN_TABS = 5

export type Tab = {
  documentId: number
  title: string
  lastAccessedAt: number
}

type TabsContextValue = {
  tabs: Tab[]
  openIds: Set<number>
  visitDocument: (documentId: number, title: string) => void
}

const TabsContext = createContext<TabsContextValue | null>(null)

export function TabsProvider({ children }: { children: ReactNode }) {
  const [tabs, setTabs] = useState<Tab[]>([])

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

  const openIds = useMemo(() => new Set(tabs.map((tab) => tab.documentId)), [tabs])

  const value = useMemo(() => ({ tabs, openIds, visitDocument }), [tabs, openIds, visitDocument])

  return <TabsContext.Provider value={value}>{children}</TabsContext.Provider>
}

export function useTabs() {
  const ctx = useContext(TabsContext)
  if (!ctx) throw new Error('useTabs must be used within a TabsProvider')
  return ctx
}
