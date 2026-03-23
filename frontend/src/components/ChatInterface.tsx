import { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { queryChatStream, listStatements, type Statement } from '../api/client'
import { useQuery } from '@tanstack/react-query'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sql_used?: string | null
  sources?: string[]
}

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [expandedSql, setExpandedSql] = useState<number | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const { data: statements } = useQuery({
    queryKey: ['statements'],
    queryFn: () => listStatements().then(r => r.data),
  })

  const doneStatements = statements?.filter((s: Statement) => s.status === 'done') ?? []

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async () => {
    const q = input.trim()
    if (!q || loading) return

    setMessages(prev => [...prev, { role: 'user', content: q }])
    setInput('')
    setLoading(true)

    // Add an empty assistant message that we'll stream into
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      let sql: string | null = null
      let srcs: string[] = []

      await queryChatStream(
        q,
        selectedIds.length > 0 ? selectedIds : undefined,
        (meta) => {
          sql = meta.sql_used
          srcs = meta.sources
          // Update the placeholder with metadata
          setMessages(prev => {
            const next = [...prev]
            next[next.length - 1] = { ...next[next.length - 1], sql_used: sql, sources: srcs }
            return next
          })
        },
        (chunk) => {
          setMessages(prev => {
            const next = [...prev]
            const last = next[next.length - 1]
            next[next.length - 1] = { ...last, content: last.content + chunk }
            return next
          })
        },
      )
    } catch {
      setMessages(prev => {
        const next = [...prev]
        next[next.length - 1] = { role: 'assistant', content: 'Sorry, something went wrong. Please try again.' }
        return next
      })
    } finally {
      setLoading(false)
    }
  }

  const toggleStatement = (id: string) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Statement selector */}
      {doneStatements.length > 0 && (
        <div className="border-b border-gray-100 px-4 py-2 flex gap-2 flex-wrap">
          <span className="text-xs text-gray-400 self-center">Filter by:</span>
          {doneStatements.map((s: Statement) => (
            <button
              key={s.id}
              onClick={() => toggleStatement(s.id)}
              className={`text-xs px-3 py-1 rounded-full border transition
                ${selectedIds.includes(s.id)
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : 'border-gray-200 text-gray-600 hover:border-indigo-400'}`}
            >
              {s.filename}
            </button>
          ))}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-400 mt-10">
            <div className="text-5xl mb-3">💬</div>
            <p className="font-medium text-gray-600">Ask Tracely anything about your spending</p>
            <div className="mt-4 space-y-2 text-sm">
              {[
                'How much did I spend on Swiggy in March?',
                'List all subscriptions this month',
                'What were my top 5 merchants?',
                'Compare food spending between Feb and March',
              ].map(q => (
                <button
                  key={q}
                  onClick={() => { setInput(q); }}
                  className="block mx-auto text-indigo-500 hover:text-indigo-700 hover:underline"
                >
                  "{q}"
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm
              ${m.role === 'user'
                ? 'bg-indigo-600 text-white rounded-br-sm'
                : 'bg-white border border-gray-200 text-gray-800 rounded-bl-sm shadow-sm'}`}>
              {m.role === 'user' ? (
                <p className="whitespace-pre-wrap">{m.content}</p>
              ) : (
                <div className="prose prose-sm max-w-none prose-table:text-xs prose-td:py-1 prose-th:py-1">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                </div>
              )}

              {m.role === 'assistant' && m.sql_used && (
                <div className="mt-2 border-t border-gray-100 pt-2">
                  <button
                    onClick={() => setExpandedSql(expandedSql === i ? null : i)}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >
                    {expandedSql === i ? '▲ Hide' : '▼ How I answered'}
                  </button>
                  {expandedSql === i && (
                    <pre className="mt-1 text-xs bg-gray-50 rounded p-2 overflow-x-auto text-gray-600">
                      {m.sql_used}
                    </pre>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Show dots only while waiting for first token */}
        {loading && messages[messages.length - 1]?.content === '' && (
          <div className="flex justify-start -mt-2">
            <div className="bg-white border border-gray-200 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm">
              <div className="flex gap-1">
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="w-2 h-2 bg-gray-300 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="border-t border-gray-100 p-4">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder="Ask about your spending..."
            className="flex-1 border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
            disabled={loading}
          />
          <button
            onClick={send}
            disabled={loading || !input.trim()}
            className="bg-indigo-600 text-white px-5 py-2.5 rounded-xl hover:bg-indigo-700 transition disabled:opacity-50 text-sm font-medium"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
