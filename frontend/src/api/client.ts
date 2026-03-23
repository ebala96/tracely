import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// --- Types ---

export interface Statement {
  id: string
  filename: string
  bank_name: string | null
  period_start: string | null
  period_end: string | null
  status: 'pending' | 'processing' | 'done' | 'failed'
  uploaded_at: string
  processed_at: string | null
  error_msg: string | null
}

export interface Category {
  id: number
  name: string
  slug: string
  icon: string
  colour: string
  parent_id: number | null
}

export interface Transaction {
  id: string
  statement_id: string
  category_id: number | null
  subcategory_id: number | null
  date: string
  description: string
  merchant: string | null
  amount: number
  txn_type: 'debit' | 'credit'
  balance: number | null
  ref_number: string | null
  user_corrected: boolean
  category?: Category
  subcategory?: Category
}

export interface QueryResponse {
  answer: string
  sources: string[]
  sql_used: string | null
}

export interface MonthlyStat {
  month: string
  total_debit: number
  total_credit: number
}

export interface CategoryStat {
  category: string
  slug: string
  colour: string
  icon: string
  total: number
  count: number
}

export interface MerchantStat {
  merchant: string
  total: number
  count: number
}

export interface PaginatedTransactions {
  items: Transaction[]
  total: number
  page: number
  page_size: number
}

// --- Statements ---

export interface UploadResponse {
  statement_id: string
  status: string
}

export const uploadStatement = (file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post<UploadResponse>('/upload', form)
}

export const getStatement = (id: string) =>
  api.get<Statement>(`/statements/${id}`)

export const listStatements = () =>
  api.get<Statement[]>('/statements')

export const deleteStatement = (id: string) =>
  api.delete(`/statements/${id}`)

export const deleteAllStatements = () =>
  api.delete('/statements')

// --- Transactions ---

export const getTransactions = (params: {
  page?: number
  page_size?: number
  statement_id?: string
  category_slug?: string
  merchant?: string
  date_from?: string
  date_to?: string
  txn_type?: string
  amount_min?: number
  amount_max?: number
}) => api.get<PaginatedTransactions>('/transactions', { params })

// --- Query ---

export const queryChat = (question: string, statement_ids?: string[]) =>
  api.post<QueryResponse>('/query', { question, statement_ids })

export interface StreamMeta {
  sql_used: string | null
  sources: string[]
}

export async function queryChatStream(
  question: string,
  statementIds: string[] | undefined,
  onMeta: (meta: StreamMeta) => void,
  onChunk: (chunk: string) => void,
): Promise<void> {
  const resp = await fetch('/api/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, statement_ids: statementIds }),
  })
  if (!resp.ok || !resp.body) throw new Error('Stream request failed')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.meta) onMeta(data.meta)
        else if (data.chunk != null) onChunk(data.chunk)
      } catch { /* ignore malformed lines */ }
    }
  }
}

// --- Categories ---

export const listCategories = () =>
  api.get<Category[]>('/categories')

export const createCategory = (data: { name: string; slug: string; icon?: string; colour?: string }) =>
  api.post<Category>('/categories', data)

export const updateCategory = (id: number, data: { name?: string; icon?: string; colour?: string }) =>
  api.patch<Category>(`/categories/${id}`, data)

export const deleteCategory = (id: number) =>
  api.delete(`/categories/${id}`)

export const applyPattern = (txnId: string) =>
  api.post<{ updated: number; pattern: string }>(`/transactions/${txnId}/apply-pattern`)

export const bulkUpdateCategory = (
  transactionIds: string[],
  categoryId: number | null,
  subcategoryId: number | null = null,
) =>
  api.patch<{ updated: number }>('/transactions/bulk-category', {
    transaction_ids: transactionIds,
    category_id:     categoryId,
    subcategory_id:  subcategoryId,
  })

export interface RecurringTransaction {
  merchant:      string
  frequency:     'monthly' | 'weekly' | 'irregular'
  avg_amount:    number
  occurrences:   number
  last_date:     string
  next_expected: string | null
}

export const getRecurring = (params: { statement_id?: string }) =>
  api.get<RecurringTransaction[]>('/analytics/recurring', { params })

export const updateTransactionCategory = (
  txnId: string,
  categoryId: number | null,
  subcategoryId: number | null = null,
) =>
  api.patch<Transaction>(`/transactions/${txnId}/category`, {
    category_id: categoryId,
    subcategory_id: subcategoryId,
  })

// --- Analytics ---

export interface MonthlySummary {
  debit: number
  credit: number
  count: number
}

export interface SummaryStats {
  this_month: MonthlySummary
  last_month: MonthlySummary
  change_pct: number | null
  savings: number
  savings_rate: number | null
  period_label: string
  prev_label: string
}

export const getSummary = (params: { statement_id?: string }) =>
  api.get<SummaryStats>('/analytics/summary', { params })

export const getMonthlyStats = (params: { year?: number; statement_id?: string }) =>
  api.get<MonthlyStat[]>('/analytics/monthly', { params })

export const getCategoryStats = (params: {
  from?: string
  to?: string
  statement_id?: string
  txn_type?: 'debit' | 'credit'
}) => api.get<CategoryStat[]>('/analytics/categories', { params })

export const getMerchantStats = (params: { limit?: number; statement_id?: string }) =>
  api.get<MerchantStat[]>('/analytics/merchants', { params })
