import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { logout } from './api'
import { useCurrentUser } from './AuthGate'
import { GrammarLegendModal } from './GrammarLegend'
import { JmdictSearch } from './JmdictSearch'
import { PosLegendModal } from './PosLegend'
import { useTabs } from './TabsContext'

export function Layout() {
  const { tabs } = useTabs()
  const user = useCurrentUser()
  const [showPosLegend, setShowPosLegend] = useState(false)
  const [showGrammarLegend, setShowGrammarLegend] = useState(false)

  return (
    <div className="app-layout">
      <nav className="sidebar">
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
      <aside className="right-panel">
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
