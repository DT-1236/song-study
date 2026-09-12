import { NavLink, Outlet } from 'react-router-dom'
import { JmdictSearch } from './JmdictSearch'
import { PosLegend } from './PosLegend'
import { useTabs } from './TabsContext'

export function Layout() {
  const { tabs } = useTabs()

  return (
    <div className="app-layout">
      <nav className="sidebar">
        <NavLink to="/new" className={({ isActive }) => (isActive ? 'active' : '')}>
          New Document
        </NavLink>
        <NavLink to="/documents" end className={({ isActive }) => (isActive ? 'active' : '')}>
          Existing Documents
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
      </nav>
      <main className="content">
        <Outlet />
      </main>
      <aside className="right-panel">
        <PosLegend />
        <JmdictSearch />
      </aside>
    </div>
  )
}
