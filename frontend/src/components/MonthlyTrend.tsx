import { useState } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { getMonthlyStats } from '../api/client'

interface Props {
  statementId?: string
}

export default function MonthlyTrend({ statementId }: Props) {
  const [year, setYear] = useState(new Date().getFullYear())
  const [showDebit, setShowDebit] = useState(true)
  const [showCredit, setShowCredit] = useState(true)

  const { data, isLoading } = useQuery({
    queryKey: ['monthly-stats', statementId, year],
    queryFn: () => getMonthlyStats({ year, statement_id: statementId }).then(r => r.data),
  })

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="font-semibold text-gray-800">Monthly Overview</h2>
        <div className="flex items-center gap-3">
          <div className="flex gap-2">
            <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
              <input type="checkbox" checked={showDebit} onChange={e => setShowDebit(e.target.checked)} className="accent-red-500" />
              Debit
            </label>
            <label className="flex items-center gap-1 text-xs text-gray-600 cursor-pointer">
              <input type="checkbox" checked={showCredit} onChange={e => setShowCredit(e.target.checked)} className="accent-green-500" />
              Credit
            </label>
          </div>
          <select
            value={year}
            onChange={e => setYear(Number(e.target.value))}
            className="border border-gray-200 rounded px-2 py-1 text-xs"
          >
            {[2023, 2024, 2025, 2026].map(y => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        </div>
      </div>

      {isLoading && <div className="h-56 flex items-center justify-center text-gray-400">Loading...</div>}

      {!isLoading && (!data || data.length === 0) && (
        <div className="h-56 flex items-center justify-center text-gray-400 text-sm">No data for {year}</div>
      )}

      {!isLoading && data && data.length > 0 && (
        <ResponsiveContainer width="100%" height={220}>
          <AreaChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="debitGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#ef4444" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="creditGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#22c55e" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis dataKey="month" tick={{ fontSize: 12 }} />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `₹${(v / 1000).toFixed(0)}k`} />
            <Tooltip
              formatter={(value: number, name: string) => [
                `₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`,
                name === 'total_debit' ? 'Debit' : 'Credit',
              ]}
            />
            <Legend formatter={v => v === 'total_debit' ? 'Debit' : 'Credit'} />
            {showDebit && (
              <Area type="monotone" dataKey="total_debit" stroke="#ef4444" fill="url(#debitGrad)" strokeWidth={2} />
            )}
            {showCredit && (
              <Area type="monotone" dataKey="total_credit" stroke="#22c55e" fill="url(#creditGrad)" strokeWidth={2} />
            )}
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
