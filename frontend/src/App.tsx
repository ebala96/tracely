import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Upload from './pages/Upload'
import Transactions from './pages/Transactions'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Categories from './pages/Categories'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
})

const navItems = [
  { to: '/dashboard', label: '📊 Dashboard' },
  { to: '/upload', label: '📤 Upload' },
  { to: '/transactions', label: '📋 Transactions' },
  { to: '/chat', label: '💬 Chat' },
  { to: '/categories', label: '🏷️ Categories' },
]

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="min-h-screen bg-gray-50 flex flex-col">
          <nav className="bg-white border-b border-gray-200 sticky top-0 z-10">
            <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
              <span className="font-bold text-gray-800 text-lg tracking-tight">
                💰 Tracely
              </span>
              <div className="flex gap-1">
                {navItems.map(({ to, label }) => (
                  <NavLink
                    key={to}
                    to={to}
                    className={({ isActive }) =>
                      `px-3 py-1.5 rounded-lg text-sm font-medium transition-colors
                      ${isActive
                        ? 'bg-indigo-50 text-indigo-700'
                        : 'text-gray-600 hover:bg-gray-100 hover:text-gray-800'}`
                    }
                  >
                    {label}
                  </NavLink>
                ))}
              </div>
            </div>
          </nav>
          <main className="flex-1">
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/upload" element={<Upload />} />
              <Route path="/transactions" element={<Transactions />} />
              <Route path="/chat" element={<Chat />} />
              <Route path="/categories" element={<Categories />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
