import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listStatements, getMerchantStats, getRecurring, getSummary } from '../api/client'
import CategoryChart from '../components/CategoryChart'
import MonthlyTrend from '../components/MonthlyTrend'
import TransactionTable from '../components/TransactionTable'

export default function Dashboard() {
  const [selectedStatement, setSelectedStatement] = useState<string>('')
  const [filterCategory, setFilterCategory] = useState<string | undefined>()

  const { data: statements } = useQuery({
    queryKey: ['statements'],
    queryFn: () => listStatements().then(r => r.data),
  })

  const { data: topMerchants } = useQuery({
    queryKey: ['merchant-stats', selectedStatement],
    queryFn: () => getMerchantStats({ limit: 5, statement_id: selectedStatement || undefined }).then(r => r.data),
  })

  const { data: recurring } = useQuery({
    queryKey: ['recurring', selectedStatement],
    queryFn: () => getRecurring({ statement_id: selectedStatement || undefined }).then(r => r.data),
  })

  const { data: summary } = useQuery({
    queryKey: ['summary', selectedStatement],
    queryFn: () => getSummary({ statement_id: selectedStatement || undefined }).then(r => r.data),
  })

  const doneStatements = statements?.filter(s => s.status === 'done') ?? []

  if (doneStatements.length === 0) {
    return (
      <div className="max-w-2xl mx-auto py-20 text-center text-gray-400">
        <div className="text-6xl mb-4">📊</div>
        <p className="text-lg font-medium text-gray-600">No data yet</p>
        <p className="text-sm mt-1">Upload a bank statement to see your dashboard</p>
      </div>
    )
  }

  return (
    <div className="max-w-6xl mx-auto py-8 px-4 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-800">Dashboard</h1>
        <select
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm"
          value={selectedStatement}
          onChange={e => setSelectedStatement(e.target.value)}
        >
          <option value="">All statements</option>
          {doneStatements.map(s => (
            <option key={s.id} value={s.id}>
              {s.filename} {s.period_start ? `(${s.period_start})` : ''}
            </option>
          ))}
        </select>
      </div>

      {/* Summary cards */}
      {summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Total spend */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Spent — {summary.period_label}
            </p>
            <p className="text-2xl font-bold text-red-600">
              ₹{summary.this_month.debit.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </p>
            <p className="text-xs text-gray-500 mt-1">{summary.this_month.count} transactions</p>
          </div>

          {/* vs previous period */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Spent — {summary.prev_label}
            </p>
            <p className="text-2xl font-bold text-gray-700">
              ₹{summary.last_month.debit.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </p>
            {summary.change_pct !== null && (
              <p className={`text-xs mt-1 font-medium ${summary.change_pct > 0 ? 'text-red-500' : 'text-green-600'}`}>
                {summary.change_pct > 0 ? '▲' : '▼'} {Math.abs(summary.change_pct)}% month-on-month
              </p>
            )}
          </div>

          {/* Income */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Income — {summary.period_label}
            </p>
            <p className="text-2xl font-bold text-green-600">
              ₹{summary.this_month.credit.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </p>
            <p className="text-xs text-gray-500 mt-1">{summary.last_month.count} txns prev month</p>
          </div>

          {/* Net savings */}
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">
              Net savings — {summary.period_label}
            </p>
            <p className={`text-2xl font-bold ${summary.savings >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {summary.savings >= 0 ? '+' : '−'}₹{Math.abs(summary.savings).toLocaleString('en-IN', { maximumFractionDigits: 0 })}
            </p>
            {summary.savings_rate !== null && (
              <p className="text-xs text-gray-500 mt-1">{summary.savings_rate}% savings rate</p>
            )}
          </div>
        </div>
      )}

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <CategoryChart
          statementId={selectedStatement || undefined}
          onCategoryClick={slug => setFilterCategory(slug === filterCategory ? undefined : slug)}
        />
        <MonthlyTrend statementId={selectedStatement || undefined} />
      </div>

      {/* Top merchants */}
      {topMerchants && topMerchants.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Top Merchants</h2>
          <div className="space-y-2">
            {topMerchants.map((m, i) => {
              const max = topMerchants[0].total
              return (
                <div key={i} className="flex items-center gap-3">
                  <span className="text-xs text-gray-400 w-4">{i + 1}</span>
                  <span className="text-sm text-gray-700 w-36 truncate">{m.merchant}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-indigo-500 h-2 rounded-full transition-all"
                      style={{ width: `${(m.total / max) * 100}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium text-gray-700 text-right w-24">
                    ₹{m.total.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </span>
                  <span className="text-xs text-gray-400 w-16 text-right">{m.count} txns</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Recurring transactions */}
      {recurring && recurring.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-800 mb-4">Recurring / Subscriptions</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {recurring.map((r, i) => (
              <div key={i} className="flex items-start gap-3 p-3 rounded-lg border border-gray-100 bg-gray-50">
                <div className={`mt-0.5 w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                  r.frequency === 'monthly' ? 'bg-violet-500' :
                  r.frequency === 'weekly'  ? 'bg-blue-500' : 'bg-gray-400'
                }`} />
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{r.merchant}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    ₹{r.avg_amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })} avg
                    · {r.occurrences}× · <span className="capitalize">{r.frequency}</span>
                  </p>
                  {r.next_expected && (
                    <p className="text-xs text-indigo-500 mt-0.5">Next: {r.next_expected}</p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transactions filtered by category */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-800">
            Transactions {filterCategory ? `— ${filterCategory}` : ''}
          </h2>
          {filterCategory && (
            <button onClick={() => setFilterCategory(undefined)} className="text-xs text-gray-400 hover:text-gray-600">
              Clear filter ✕
            </button>
          )}
        </div>
        <TransactionTable
          statementId={selectedStatement || undefined}
          categorySlug={filterCategory}
        />
      </div>
    </div>
  )
}
