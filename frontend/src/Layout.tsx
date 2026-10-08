import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, matchPath, useLocation } from 'react-router-dom'
import { logout } from './api'
import { useCurrentUser } from './AuthGate'
import { GrammarLegendModal } from './GrammarLegend'
import { JmdictSearch } from './JmdictSearch'
import { NARROW_SCREEN, useMediaQuery } from './media'
import { PosLegendModal } from './PosLegend'
import { useTabs } from './TabsContext'

const PAGE_NAMES: Record<string, string> = {
  '/new': 'New Document',
  '/documents': 'Existing Documents',
  '/study': 'Study',
}

type Drawer = 'nav' | 'lookup' | null

export function Layout() {
  const { tabs } = useTabs()
  const { pathname } = useLocation()
  const narrow = useMediaQuery(NARROW_SCREEN)
  const [drawer, setDrawer] = useState<Drawer>(null)
  const navRef = useRef<HTMLElement>(null)
  const lookupRef = useRef<HTMLElement>(null)
  const user = useCurrentUser()
  const [showPosLegend, setShowPosLegend] = useState(false)
  const [showGrammarLegend, setShowGrammarLegend] = useState(false)

  // Navigating closes whichever drawer is open.
  useEffect(() => {
    setDrawer(null)
  }, [pathname])

  useEffect(() => {
    if (drawer === null) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setDrawer(null)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [drawer])

  // A closed drawer on a narrow screen is skipped by Tab and screen readers.
  // React 18 has no `inert` prop, so it's set on the element.
  useEffect(() => {
    if (navRef.current) navRef.current.inert = narrow && drawer !== 'nav'
    if (lookupRef.current)
      lookupRef.current.inert = narrow && drawer !== 'lookup'
  }, [narrow, drawer])

  useEffect(() => {
    if (drawer === 'lookup')
      lookupRef.current?.querySelector('input')?.focus({ preventScroll: true })
  }, [drawer])

  const documentId = matchPath('/documents/:id/*', pathname)?.params.id
  const pageName =
    PAGE_NAMES[pathname] ??
    tabs.find((tab) => String(tab.documentId) === documentId)?.title ??
    ''

  return (
    <div className="app-layout">
      <header className="top-bar">
        <button
          type="button"
          aria-label="Menu"
          aria-expanded={drawer === 'nav'}
          onClick={() => setDrawer('nav')}
        >
          ☰
        </button>
        <span className="top-bar-title">{pageName}</span>
        <button
          type="button"
          aria-expanded={drawer === 'lookup'}
          onClick={() => setDrawer('lookup')}
        >
          Lookup
        </button>
      </header>
      {drawer !== null && (
        <div className="drawer-backdrop" onClick={() => setDrawer(null)} />
      )}
      <nav
        ref={navRef}
        className={`sidebar${drawer === 'nav' ? ' drawer-open' : ''}`}
      >
        <div className="sidebar-scroll">
          <NavLink
            to="/new"
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            New Document
          </NavLink>
          <NavLink
            to="/documents"
            end
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            Existing Documents
          </NavLink>
          <NavLink
            to="/study"
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            Study
          </NavLink>

          {tabs.length > 0 && (
            <div className="sidebar-tabs">
              {tabs.map((tab) => (
                <NavLink
                  key={tab.documentId}
                  to={`/documents/${tab.documentId}`}
                  className={({ isActive }) => (isActive ? 'active' : '')}
                  title={tab.title}
                >
                  {tab.title}
                </NavLink>
              ))}
            </div>
          )}
        </div>

        <div className="sidebar-references">
          <div className="sidebar-section-title">References</div>
          <button type="button" onClick={() => setShowPosLegend(true)}>
            Parts of Speech
          </button>
          <button type="button" onClick={() => setShowGrammarLegend(true)}>
            Grammar Rules
          </button>
          <div className="sidebar-section-title">{user.name}</div>
          <button
            type="button"
            onClick={() => logout().then(() => window.location.reload())}
          >
            Log out
          </button>
        </div>
      </nav>
      <main className="content">
        <div className="content-inner">
          <Outlet />
        </div>
      </main>
      <aside
        ref={lookupRef}
        className={`right-panel${drawer === 'lookup' ? ' drawer-open' : ''}`}
      >
        <JmdictSearch />
      </aside>
      <PosLegendModal
        open={showPosLegend}
        onClose={() => setShowPosLegend(false)}
      />
      <GrammarLegendModal
        open={showGrammarLegend}
        onClose={() => setShowGrammarLegend(false)}
      />
    </div>
  )
}
