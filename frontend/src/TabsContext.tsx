import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

const MAX_OPEN_TABS = 5

export type Tab = {
  documentId: number
  title: string
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
      const next = prev.filter((tab) => tab.documentId !== documentId)
      next.push({ documentId, title })

      if (next.length > MAX_OPEN_TABS) {
        next.shift()
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
