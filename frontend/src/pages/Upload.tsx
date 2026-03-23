import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PdfUploader from '../components/PdfUploader'
import { listStatements, deleteStatement, deleteAllStatements, type Statement } from '../api/client'
import { useQuery, useQueryClient } from '@tanstack/react-query'

export default function Upload() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [doneCount, setDoneCount] = useState(0)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [clearingAll, setClearingAll] = useState(false)

  const { data: statements, refetch } = useQuery({
    queryKey: ['statements'],
    queryFn: () => listStatements().then(r => r.data),
  })

  const handleDone = (s: Statement) => {
    setDoneCount(c => c + 1)
    refetch()
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this statement and all its transactions?')) return
    setDeletingId(id)
    try {
      await deleteStatement(id)
      queryClient.invalidateQueries({ queryKey: ['statements'] })
      queryClient.invalidateQueries({ queryKey: ['transactions'] })
      queryClient.invalidateQueries({ queryKey: ['category-stats'] })
      queryClient.invalidateQueries({ queryKey: ['monthly-stats'] })
      queryClient.invalidateQueries({ queryKey: ['merchant-stats'] })
    } finally {
      setDeletingId(null)
    }
  }

  const handleClearAll = async () => {
    if (!confirm('Delete ALL statements, transactions and embeddings? This cannot be undone.')) return
    setClearingAll(true)
    try {
      await deleteAllStatements()
      queryClient.invalidateQueries()
      setDoneCount(0)
    } finally {
      setClearingAll(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto py-10 px-4">
      <h1 className="text-2xl font-bold text-gray-800 mb-1">Upload Statements</h1>
      <p className="text-gray-500 text-sm mb-6">Upload your bank statement PDFs. They'll be parsed and indexed automatically.</p>

      <PdfUploader onDone={handleDone} />

      {doneCount > 0 && (
        <div className="mt-6 p-4 bg-green-50 border border-green-200 rounded-lg flex items-center justify-between">
          <p className="text-green-700 text-sm font-medium">
            {doneCount} statement{doneCount > 1 ? 's' : ''} processed successfully!
          </p>
          <button
            onClick={() => navigate('/chat')}
            className="text-sm bg-green-600 text-white px-4 py-1.5 rounded-lg hover:bg-green-700 transition"
          >
            Ask questions →
          </button>
        </div>
      )}

      {statements && statements.length > 0 && (
        <div className="mt-8">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-600 uppercase tracking-wide">Previous Uploads</h2>
            <button
              onClick={handleClearAll}
              disabled={clearingAll}
              className="text-xs text-red-500 hover:text-red-700 hover:underline disabled:opacity-50 transition"
            >
              {clearingAll ? 'Clearing...' : '🗑 Clear all'}
            </button>
          </div>
          <ul className="space-y-2">
            {statements.map(s => (
              <li key={s.id} className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{s.filename}</p>
                  <p className="text-xs text-gray-400">
                    {s.bank_name ?? 'Unknown bank'}
                    {s.period_start && ` · ${s.period_start} → ${s.period_end}`}
                  </p>
                </div>
                <div className="flex items-center gap-3 ml-4">
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full
                    ${s.status === 'done' ? 'bg-green-100 text-green-700' :
                      s.status === 'failed' ? 'bg-red-100 text-red-700' :
                      s.status === 'processing' ? 'bg-yellow-100 text-yellow-700' :
                      'bg-gray-100 text-gray-600'}`}>
                    {s.status}
                  </span>
                  <button
                    onClick={() => handleDelete(s.id)}
                    disabled={deletingId === s.id}
                    className="text-gray-400 hover:text-red-500 transition disabled:opacity-50 text-sm"
                    title="Delete statement"
                  >
                    {deletingId === s.id ? '...' : '✕'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
