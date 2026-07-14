import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Dashboard } from './pages/Dashboard'
import { Positions } from './pages/Positions'
import { Review } from './pages/Review'
import { StockAnalysis } from './pages/StockAnalysis'
import { Trades } from './pages/Trades'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="stock" element={<StockAnalysis />} />
          <Route path="positions" element={<Positions />} />
          <Route path="trades" element={<Trades />} />
          <Route path="review" element={<Review />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
