import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { listStatements } from '../api/client'
import TransactionTable from '../components/TransactionTable'

export default function Transactions() {
  const [selectedStatement, setSelectedStatement] = useState<string>('')

  const { data: statements } = useQuery({
    queryKey: ['statements'],
    queryFn: () => listStatements().then(r => r.data),
  })

  const doneStatements = statements?.filter(s => s.status === 'done') ?? []

  return (
    <div className="max-w-6xl mx-auto py-10 px-4">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-800">Transactions</h1>
          <p className="text-gray-500 text-sm">Browse and filter your transaction history</p>
        </div>
        {doneStatements.length > 0 && (
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
        )}
      </div>

      {doneStatements.length === 0 ? (
        <div className="text-center py-20 text-gray-400">
          <div className="text-5xl mb-4">📭</div>
          <p className="font-medium">No statements uploaded yet</p>
          <p className="text-sm mt-1">Upload a bank statement PDF to get started</p>
        </div>
      ) : (
        <TransactionTable statementId={selectedStatement || undefined} />
      )}
    </div>
  )
}
