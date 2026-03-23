import { useState } from 'react'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'
import { useQuery } from '@tanstack/react-query'
import { getCategoryStats } from '../api/client'

interface Props {
  statementId?: string
  onCategoryClick?: (slug: string) => void
}

export default function CategoryChart({ statementId, onCategoryClick }: Props) {
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [txnType, setTxnType] = useState<'debit' | 'credit'>('debit')

  const { data, isLoading } = useQuery({
    queryKey: ['category-stats', statementId, dateFrom, dateTo, txnType],
    queryFn: () => getCategoryStats({
      statement_id: statementId,
      from: dateFrom || undefined,
      to: dateTo || undefined,
      txn_type: txnType,
    }).then(r => r.data),
  })

  const chartData = data?.map(c => ({
    name: `${c.icon} ${c.category}`,
    slug: c.slug,
    value: c.total,
    colour: c.colour,
    count: c.count,
  })) ?? []

  const total = chartData.reduce((s, c) => s + c.value, 0)

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold text-gray-800">
            {txnType === 'debit' ? 'Spending' : 'Income'} by Category
          </h2>
          <div className="flex rounded-lg border border-gray-200 overflow-hidden text-xs">
            <button
              onClick={() => setTxnType('debit')}
              className={`px-3 py-1 transition ${txnType === 'debit' ? 'bg-red-500 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}
            >Expenses</button>
            <button
              onClick={() => setTxnType('credit')}
              className={`px-3 py-1 transition ${txnType === 'credit' ? 'bg-green-500 text-white' : 'bg-white text-gray-500 hover:bg-gray-50'}`}
            >Income</button>
          </div>
        </div>
        <div className="flex gap-2">
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-xs" />
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            className="border border-gray-200 rounded px-2 py-1 text-xs" />
        </div>
      </div>

      {isLoading && <div className="h-64 flex items-center justify-center text-gray-400">Loading...</div>}

      {!isLoading && chartData.length === 0 && (
        <div className="h-64 flex items-center justify-center text-gray-400 text-sm">No data yet</div>
      )}

      {!isLoading && chartData.length > 0 && (
        <div className="flex gap-4 items-start">
          {/* Pie chart — fixed size, no legend */}
          <div className="flex-shrink-0 w-56 h-56">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
                <Pie
                  data={chartData}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={100}
                  onClick={d => onCategoryClick?.(d.slug)}
                  className="cursor-pointer"
                >
                  {chartData.map((c, i) => (
                    <Cell key={i} fill={c.colour} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number) =>
                    [`₹${value.toLocaleString('en-IN', { minimumFractionDigits: 2 })}`, 'Spent']}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          {/* Category list as legend */}
          <div className="flex-1 min-w-0 space-y-1 overflow-y-auto max-h-56">
            {chartData.map((c, i) => (
              <div
                key={i}
                className="flex items-center justify-between text-sm hover:bg-gray-50 rounded px-2 py-1 cursor-pointer"
                onClick={() => onCategoryClick?.(c.slug)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: c.colour }} />
                  <span className="text-gray-700 truncate">{c.name}</span>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 ml-2">
                  <span className="font-medium text-gray-800 text-xs">
                    ₹{c.value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
                  </span>
                  <span className="text-gray-400 text-xs w-9 text-right">
                    {total > 0 ? ((c.value / total) * 100).toFixed(0) : 0}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
