import { Navigate, Route, BrowserRouter, Routes } from 'react-router-dom'
import './App.css'
import { Layout } from './Layout'
import { NewDocumentForm } from './NewDocumentForm'
import { DocumentsListPage } from './DocumentsListPage'
import { DocumentViewPage } from './DocumentViewPage'
import { TabsProvider } from './TabsContext'

function App() {
  return (
    <BrowserRouter>
      <TabsProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/new" replace />} />
            <Route path="new" element={<NewDocumentForm />} />
            <Route path="documents" element={<DocumentsListPage />} />
            <Route path="documents/:id" element={<DocumentViewPage />} />
          </Route>
        </Routes>
      </TabsProvider>
    </BrowserRouter>
  )
}

export default App
