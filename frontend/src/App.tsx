import {
  Navigate,
  Route,
  RouterProvider,
  createBrowserRouter,
  createRoutesFromElements,
} from 'react-router-dom'
import './App.css'
import { AuthGate } from './AuthGate'
import { Layout } from './Layout'
import { NewDocumentForm } from './NewDocumentForm'
import { DocumentsListPage } from './DocumentsListPage'
import { DocumentViewPage } from './DocumentViewPage'
import { TabsProvider } from './TabsContext'

// A data router, which a page needs to ask before it's left with unsaved
// changes (useBlocker).
const router = createBrowserRouter(
  createRoutesFromElements(
    <Route
      element={
        <TabsProvider>
          <Layout />
        </TabsProvider>
      }
    >
      <Route index element={<Navigate to="/new" replace />} />
      <Route path="new" element={<NewDocumentForm />} />
      <Route path="documents" element={<DocumentsListPage />} />
      <Route path="documents/:id" element={<DocumentViewPage />} />
    </Route>,
  ),
)

function App() {
  return (
    <AuthGate>
      <RouterProvider router={router} />
    </AuthGate>
  )
}

export default App
