import { useState, useRef, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getTransactions, listCategories, updateTransactionCategory, applyPattern, bulkUpdateCategory, type Transaction, type Category } from '../api/client'
import { format } from 'date-fns'

interface Props {
  statementId?: string
  categorySlug?: string
}

const PAGE_SIZE = 20

function CategoryPicker({ transaction, categories }: { transaction: Transaction; categories: Category[] }) {
  const [open, setOpen] = useState(false)
  const [expandedParent, setExpandedParent] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [applying, setApplying] = useState(false)
  const [applyResult, setApplyResult] = useState<{ updated: number; pattern: string } | null>(null)
  const ref = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  // Separate parents and subcategories
  const parents = categories.filter(c => c.parent_id === null)
  const subsByParent = categories.reduce<Record<number, Category[]>>((acc, c) => {
    if (c.parent_id !== null) {
      acc[c.parent_id] = [...(acc[c.parent_id] ?? []), c]
    }
    return acc
  }, {})

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setExpandedParent(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleSelect = async (cat: Category | null, sub: Category | null = null) => {
    setSaving(true)
    setOpen(false)
    setExpandedParent(null)
    setApplyResult(null)
    try {
      await updateTransactionCategory(transaction.id, cat?.id ?? null, sub?.id ?? null)
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['category-stats'] })
      setSaved(true)
    } finally {
      setSaving(false)
    }
  }

  const handleApplyPattern = async () => {
    setApplying(true)
    try {
      const res = await applyPattern(transaction.id)
      setApplyResult(res.data)
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['category-stats'] })
      setSaved(false)
    } finally {
      setApplying(false)
    }
  }

  // Display: prefer subcategory name if set, otherwise parent category
  const displayCat  = transaction.subcategory ?? transaction.category
  const parentCat   = transaction.category

  return (
    <div className="relative" ref={ref}>
      {/* Saved state — show "Apply Pattern" button */}
      {saved && !applyResult && (
        <div className="absolute -top-9 left-0 z-50 flex items-center gap-1 whitespace-nowrap">
          <span className="bg-green-600 text-white text-xs px-2 py-1 rounded shadow">
            Pattern saved
          </span>
          <button
            onClick={handleApplyPattern}
            disabled={applying}
            className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs px-2 py-1 rounded shadow transition disabled:opacity-60"
          >
            {applying ? 'Applying…' : 'Apply Pattern'}
          </button>
        </div>
      )}

      {/* Apply result toast */}
      {applyResult && (
        <div
          className="absolute -top-9 left-0 z-50 bg-indigo-600 text-white text-xs px-2 py-1 rounded shadow whitespace-nowrap cursor-pointer"
          onClick={() => setApplyResult(null)}
        >
          {applyResult.updated === 0
            ? `No other matches for "${applyResult.pattern}"`
            : `Applied to ${applyResult.updated} transaction${applyResult.updated > 1 ? 's' : ''} matching "${applyResult.pattern}"`
          }
        </div>
      )}

      <button
        onClick={() => { setOpen(o => !o); setExpandedParent(null) }}
        disabled={saving}
        className="group flex items-center gap-1"
        title="Click to change category"
      >
        {displayCat ? (
          <span
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium text-white hover:opacity-80 transition"
            style={{ backgroundColor: parentCat?.colour ?? displayCat.colour }}
          >
            {displayCat.icon} {displayCat.name}
            {transaction.user_corrected && <span title="Manually set" className="opacity-70">✓</span>}
            {!transaction.user_corrected && <span className="opacity-50">✎</span>}
          </span>
        ) : (
          <span className="text-xs text-gray-400 border border-dashed border-gray-300 px-2 py-0.5 rounded-full hover:border-indigo-400 hover:text-indigo-500 transition">
            + Add category
          </span>
        )}
      </button>

      {open && (
        <div className="absolute z-50 mt-1 left-0 w-60 bg-white border border-gray-200 rounded-lg shadow-lg py-1 max-h-80 overflow-y-auto">
          <button
            onClick={() => handleSelect(null)}
            className="w-full text-left px-3 py-1.5 text-xs text-gray-400 hover:bg-gray-50"
          >
            — Remove category
          </button>
          <div className="border-t border-gray-100 my-1" />

          {parents.map(parent => {
            const subs = subsByParent[parent.id] ?? []
            const isExpanded = expandedParent === parent.id
            const isCurrentParent = transaction.category?.id === parent.id

            return (
              <div key={parent.id}>
                <div className="flex items-center">
                  {/* Select parent directly */}
                  <button
                    onClick={() => handleSelect(parent)}
                    className={`flex-1 text-left px-3 py-1.5 text-xs hover:bg-gray-50 flex items-center gap-2 ${isCurrentParent && !transaction.subcategory ? 'font-semibold' : ''}`}
                  >
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: parent.colour }} />
                    {parent.icon} {parent.name}
                    {isCurrentParent && !transaction.subcategory_id && <span className="ml-auto text-indigo-500">✓</span>}
                  </button>
                  {/* Expand subcategories */}
                  {subs.length > 0 && (
                    <button
                      onClick={() => setExpandedParent(isExpanded ? null : parent.id)}
                      className="px-2 py-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-50 text-xs"
                      title={isExpanded ? 'Collapse' : 'Show subcategories'}
                    >
                      {isExpanded ? '▲' : '▶'}
                    </button>
                  )}
                </div>

                {/* Subcategories */}
                {isExpanded && subs.map(sub => (
                  <button
                    key={sub.id}
                    onClick={() => handleSelect(parent, sub)}
                    className={`w-full text-left pl-8 pr-3 py-1.5 text-xs hover:bg-indigo-50 flex items-center gap-2
                      ${transaction.subcategory_id === sub.id ? 'font-semibold text-indigo-600' : 'text-gray-600'}`}
                  >
                    <span className="text-gray-300">└</span>
                    {sub.icon} {sub.name}
                    {transaction.subcategory_id === sub.id && <span className="ml-auto text-indigo-500">✓</span>}
                  </button>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function BulkActionBar({ selected, categories, onDone, onClear }: {
  selected: string[]
  categories: Category[]
  onDone: () => void
  onClear: () => void
}) {
  const [saving, setSaving] = useState(false)
  const queryClient = useQueryClient()
  const parents = categories.filter(c => c.parent_id === null)
  const subsByParent = categories.reduce<Record<number, Category[]>>((acc, c) => {
    if (c.parent_id !== null) acc[c.parent_id] = [...(acc[c.parent_id] ?? []), c]
    return acc
  }, {})
  const [selectedParent, setSelectedParent] = useState<number | null>(null)

  const handleApply = async (catId: number | null, subId: number | null = null) => {
    setSaving(true)
    try {
      await bulkUpdateCategory(selected, catId, subId)
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['category-stats'] })
      onDone()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-200 rounded-lg px-4 py-2.5 text-sm">
      <span className="font-medium text-indigo-700">{selected.length} selected</span>
      <span className="text-indigo-300">|</span>
      <span className="text-indigo-600">Set category:</span>
      <div className="flex items-center gap-1 flex-wrap">
        {parents.map(p => (
          <div key={p.id} className="relative">
            <button
              onClick={() => subsByParent[p.id]?.length
                ? setSelectedParent(selectedParent === p.id ? null : p.id)
                : handleApply(p.id)
              }
              className="flex items-center gap-1 px-2 py-1 rounded text-xs border border-indigo-200 bg-white hover:bg-indigo-50 transition"
            >
              <span className="w-2 h-2 rounded-full" style={{ backgroundColor: p.colour }} />
              {p.icon} {p.name}
              {subsByParent[p.id]?.length > 0 && <span className="text-gray-400">▾</span>}
            </button>
            {selectedParent === p.id && subsByParent[p.id]?.length > 0 && (
              <div className="absolute top-full left-0 mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-44">
                <button
                  onClick={() => { handleApply(p.id, null); setSelectedParent(null) }}
                  className="w-full text-left px-3 py-1.5 text-xs hover:bg-gray-50 font-medium"
                >
                  {p.icon} {p.name} (no sub)
                </button>
                {subsByParent[p.id].map(s => (
                  <button
                    key={s.id}
                    onClick={() => { handleApply(p.id, s.id); setSelectedParent(null) }}
                    className="w-full text-left pl-6 pr-3 py-1.5 text-xs hover:bg-indigo-50 text-gray-600"
                  >
                    └ {s.icon} {s.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      <button onClick={onClear} className="ml-auto text-xs text-indigo-400 hover:text-indigo-600">
        {saving ? 'Saving…' : '✕ Clear'}
      </button>
    </div>
  )
}

export default function TransactionTable({ statementId, categorySlug }: Props) {
  const [page, setPage] = useState(1)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({
    merchant: '',
    txn_type: '',
    date_from: '',
    date_to: '',
    amount_min: '',
    amount_max: '',
  })

  const { data: categories } = useQuery({
    queryKey: ['categories'],
    queryFn: () => listCategories().then(r => r.data),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['transactions', page, statementId, categorySlug, filters],
    queryFn: () => getTransactions({
      page,
      page_size: PAGE_SIZE,
      statement_id: statementId,
      category_slug: categorySlug,
      merchant: filters.merchant || undefined,
      txn_type: filters.txn_type || undefined,
      date_from: filters.date_from || undefined,
      date_to: filters.date_to || undefined,
      amount_min: filters.amount_min ? Number(filters.amount_min) : undefined,
      amount_max: filters.amount_max ? Number(filters.amount_max) : undefined,
    }).then(r => r.data),
  })

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1

  const pageIds = data?.items.map(t => t.id) ?? []
  const allPageSelected = pageIds.length > 0 && pageIds.every(id => selected.has(id))

  const toggleRow = (id: string) => setSelected(prev => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })

  const toggleAll = () => setSelected(prev => {
    if (allPageSelected) {
      const next = new Set(prev)
      pageIds.forEach(id => next.delete(id))
      return next
    }
    return new Set([...prev, ...pageIds])
  })

  const exportCsv = () => {
    if (!data) return
    const rows = [
      ['Date', 'Description', 'Merchant', 'Category', 'Type', 'Amount', 'Balance'],
      ...data.items.map(t => [
        t.date, t.description, t.merchant ?? '', t.category?.name ?? '',
        t.txn_type, t.amount.toFixed(2), t.balance?.toFixed(2) ?? '',
      ]),
    ]
    const csv = rows.map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = 'transactions.csv'; a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 bg-gray-50 p-3 rounded-lg">
        <input
          type="text" placeholder="Merchant"
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.merchant}
          onChange={e => { setFilters(f => ({ ...f, merchant: e.target.value })); setPage(1) }}
        />
        <select
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.txn_type}
          onChange={e => { setFilters(f => ({ ...f, txn_type: e.target.value })); setPage(1) }}
        >
          <option value="">All types</option>
          <option value="debit">Debit</option>
          <option value="credit">Credit</option>
        </select>
        <input
          type="date" placeholder="From"
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.date_from}
          onChange={e => { setFilters(f => ({ ...f, date_from: e.target.value })); setPage(1) }}
        />
        <input
          type="date" placeholder="To"
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.date_to}
          onChange={e => { setFilters(f => ({ ...f, date_to: e.target.value })); setPage(1) }}
        />
        <input
          type="number" placeholder="Min amount"
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.amount_min}
          onChange={e => { setFilters(f => ({ ...f, amount_min: e.target.value })); setPage(1) }}
        />
        <input
          type="number" placeholder="Max amount"
          className="border border-gray-200 rounded px-3 py-1.5 text-sm"
          value={filters.amount_max}
          onChange={e => { setFilters(f => ({ ...f, amount_max: e.target.value })); setPage(1) }}
        />
        <div className="col-span-2 flex justify-end">
          <button onClick={exportCsv} className="text-sm bg-white border border-gray-200 px-3 py-1.5 rounded hover:bg-gray-100 transition">
            ⬇ Export CSV
          </button>
        </div>
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <BulkActionBar
          selected={[...selected]}
          categories={categories ?? []}
          onDone={() => { setSelected(new Set()); queryClient.invalidateQueries({ queryKey: ['transactions'] }) }}
          onClear={() => setSelected(new Set())}
        />
      )}

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full text-sm">
          <thead className="bg-gray-50 text-xs text-gray-500 uppercase tracking-wide">
            <tr>
              <th className="px-3 py-3 w-8">
                <input
                  type="checkbox"
                  checked={allPageSelected}
                  onChange={toggleAll}
                  className="rounded border-gray-300 text-indigo-600 cursor-pointer"
                />
              </th>
              <th className="px-4 py-3 text-left">Date</th>
              <th className="px-4 py-3 text-left">Description</th>
              <th className="px-4 py-3 text-left">Merchant</th>
              <th className="px-4 py-3 text-left">Category</th>
              <th className="px-4 py-3 text-right">Amount</th>
              <th className="px-4 py-3 text-right">Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {isLoading && (
              <tr><td colSpan={7} className="text-center py-10 text-gray-400">Loading...</td></tr>
            )}
            {!isLoading && data?.items.length === 0 && (
              <tr><td colSpan={7} className="text-center py-10 text-gray-400">No transactions found</td></tr>
            )}
            {data?.items.map((t: Transaction) => (
              <tr
                key={t.id}
                className={`hover:bg-gray-50 transition-colors ${selected.has(t.id) ? 'bg-indigo-50' : ''}`}
              >
                <td className="px-3 py-2.5 w-8">
                  <input
                    type="checkbox"
                    checked={selected.has(t.id)}
                    onChange={() => toggleRow(t.id)}
                    className="rounded border-gray-300 text-indigo-600 cursor-pointer"
                  />
                </td>
                <td className="px-4 py-2.5 text-gray-500 whitespace-nowrap">
                  {format(new Date(t.date), 'dd MMM yyyy')}
                </td>
                <td className="px-4 py-2.5 text-gray-700 max-w-xs truncate">{t.description}</td>
                <td className="px-4 py-2.5 text-gray-600">{t.merchant ?? '—'}</td>
                <td className="px-4 py-2.5">
                  <CategoryPicker transaction={t} categories={categories ?? []} />
                </td>
                <td className="px-4 py-2.5 text-right whitespace-nowrap">
                  <div className={`font-medium ${t.txn_type === 'debit' ? 'text-red-600' : 'text-green-600'}`}>
                    {t.txn_type === 'debit' ? '−' : '+'}₹{t.amount.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </div>
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded mt-0.5 inline-block
                    ${t.txn_type === 'debit'
                      ? 'bg-red-50 text-red-500'
                      : 'bg-green-50 text-green-600'}`}>
                    {t.txn_type === 'debit' ? 'Debit' : 'Credit'}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-right text-gray-500 whitespace-nowrap">
                  {t.balance != null ? `₹${t.balance.toLocaleString('en-IN', { minimumFractionDigits: 2 })}` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-600">
          <span>{data?.total ?? 0} transactions</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40"
            >← Prev</button>
            <span className="px-3 py-1">{page} / {totalPages}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1 border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40"
            >Next →</button>
          </div>
        </div>
      )}
    </div>
  )
}
