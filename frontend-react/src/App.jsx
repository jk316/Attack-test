import { Routes, Route, Navigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import ExperimentList from './pages/ExperimentList'
import ExperimentDetail from './pages/ExperimentDetail'
import ExperimentSummary from './pages/ExperimentSummary'
import MonitorPage from './pages/MonitorPage'

export default function App() {
  return (
    <div className="app">
      <Sidebar />
      <main>
        <Routes>
          <Route path="/" element={<ExperimentList />} />
          <Route path="/experiments/:id/summary" element={<ExperimentSummary />} />
          <Route path="/experiments/:id" element={<ExperimentDetail />} />
          <Route path="/monitor" element={<MonitorPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
