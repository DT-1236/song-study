import { useEffect, useRef, useState } from 'react'
import {
  NavLink,
  Outlet,
  matchPath,
  useLocation,
  useMatches,
} from 'react-router-dom'
import { GrammarLegendModal } from './GrammarLegend'
import { JmdictSearch } from './JmdictSearch'
import { NARROW_SCREEN, useMediaQuery } from './media'
import { PosLegendModal } from './PosLegend'
import { useTabs } from './TabsContext'
import { useInert } from './useInert'

type Drawer = 'nav' | 'lookup' | null

export function Layout() {
  const { tabs } = useTabs()
  const { pathname } = useLocation()
  const matches = useMatches()
  const narrow = useMediaQuery(NARROW_SCREEN)
  const [drawer, setDrawer] = useState<Drawer>(null)
  const navRef = useRef<HTMLElement>(null)
  const lookupRef = useRef<HTMLElement>(null)
  const lookupInputRef = useRef<HTMLInputElement>(null)
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

  // A closed drawer on a narrow screen is out of the way.
  useInert(navRef, narrow && drawer !== 'nav')
  useInert(lookupRef, narrow && drawer !== 'lookup')

  useEffect(() => {
    if (drawer === 'lookup')
      lookupInputRef.current?.focus({ preventScroll: true })
  }, [drawer])

  const documentId = matchPath('/documents/:id/*', pathname)?.params.id
  const pageName =
    (matches[matches.length - 1].handle as { title?: string } | undefined)
      ?.title ??
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
          Dict
        </button>
      </header>
      {drawer !== null && (
        <div className="drawer-backdrop" onClick={() => setDrawer(null)} />
      )}
      <nav
        ref={navRef}
        className={`sidebar${drawer === 'nav' ? ' drawer-open' : ''}`}
        // Navigating closes the drawer, but a link to the current route doesn't
        // navigate, so close it on the click itself.
        onClick={(event) => {
          if ((event.target as Element).closest('a')) setDrawer(null)
        }}
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
        </div>
        <div className="sidebar-footer">
          <NavLink
            to="/settings"
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            <span aria-hidden="true" className="sidebar-footer-icon">
              ⚙
            </span>
            Settings
          </NavLink>
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
        <JmdictSearch inputRef={lookupInputRef} />
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
