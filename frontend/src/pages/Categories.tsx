import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { listCategories, createCategory, updateCategory, deleteCategory, type Category } from '../api/client'

const PRESET_COLOURS = [
  '#F97316','#3B82F6','#8B5CF6','#EC4899',
  '#EAB308','#10B981','#6B7280','#84CC16','#9CA3AF','#EF4444',
]

const PRESET_ICONS = ['🍔','🚗','📺','🛍️','⚡','🏥','🏦','🛒','📦','✈️','🎮','💅','🏋️','🐾','🎓','🏠']

function CategoryRow({ cat, onSaved, onDeleted }: {
  cat: Category
  onSaved: () => void
  onDeleted: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(cat.name)
  const [icon, setIcon] = useState(cat.icon ?? '📦')
  const [colour, setColour] = useState(cat.colour ?? '#9CA3AF')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await updateCategory(cat.id, { name, icon, colour })
      setEditing(false)
      onSaved()
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm(`Delete "${cat.name}"? Transactions in this category will become uncategorised.`)) return
    setDeleting(true)
    try {
      await deleteCategory(cat.id)
      onDeleted()
    } finally {
      setDeleting(false)
    }
  }

  if (editing) {
    return (
      <li className="bg-white border border-indigo-200 rounded-xl p-4 space-y-3">
        <div className="flex gap-3">
          {/* Icon picker */}
          <div>
            <p className="text-xs text-gray-500 mb-1">Icon</p>
            <div className="flex flex-wrap gap-1 w-48">
              {PRESET_ICONS.map(i => (
                <button key={i} onClick={() => setIcon(i)}
                  className={`text-lg p-1 rounded ${icon === i ? 'bg-indigo-100 ring-2 ring-indigo-400' : 'hover:bg-gray-100'}`}>
                  {i}
                </button>
              ))}
            </div>
          </div>
          {/* Name + colour */}
          <div className="flex-1 space-y-2">
            <div>
              <p className="text-xs text-gray-500 mb-1">Name</p>
              <input value={name} onChange={e => setName(e.target.value)}
                className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-indigo-300" />
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">Colour</p>
              <div className="flex gap-1.5 flex-wrap">
                {PRESET_COLOURS.map(c => (
                  <button key={c} onClick={() => setColour(c)}
                    className={`w-6 h-6 rounded-full ${colour === c ? 'ring-2 ring-offset-1 ring-gray-500' : ''}`}
                    style={{ backgroundColor: c }} />
                ))}
                <input type="color" value={colour} onChange={e => setColour(e.target.value)}
                  className="w-6 h-6 rounded cursor-pointer border-0" title="Custom colour" />
              </div>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <button onClick={() => setEditing(false)} className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5">Cancel</button>
          <button onClick={handleSave} disabled={saving || !name.trim()}
            className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition">
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </li>
    )
  }

  return (
    <li className="flex items-center justify-between bg-white border border-gray-200 rounded-xl px-4 py-3 hover:border-gray-300 transition">
      <div className="flex items-center gap-3">
        <span className="w-8 h-8 rounded-full flex items-center justify-center text-white text-sm font-bold"
          style={{ backgroundColor: cat.colour }}>
          {cat.icon}
        </span>
        <div>
          <p className="text-sm font-medium text-gray-800">{cat.name}</p>
          <p className="text-xs text-gray-400">{cat.slug}</p>
        </div>
      </div>
      <div className="flex gap-2">
        <button onClick={() => setEditing(true)}
          className="text-xs text-gray-400 hover:text-indigo-600 px-2 py-1 rounded hover:bg-indigo-50 transition">
          ✎ Edit
        </button>
        <button onClick={handleDelete} disabled={deleting}
          className="text-xs text-gray-400 hover:text-red-500 px-2 py-1 rounded hover:bg-red-50 transition disabled:opacity-50">
          {deleting ? '...' : '✕ Delete'}
        </button>
      </div>
    </li>
  )
}

function AddCategoryForm({ onAdded }: { onAdded: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [icon, setIcon] = useState('📦')
  const [colour, setColour] = useState('#9CA3AF')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleNameChange = (v: string) => {
    setName(v)
    setSlug(v.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, ''))
  }

  const handleAdd = async () => {
    if (!name.trim() || !slug.trim()) return
    setSaving(true)
    setError('')
    try {
      await createCategory({ name, slug, icon, colour })
      setName(''); setSlug(''); setIcon('📦'); setColour('#9CA3AF')
      setOpen(false)
      onAdded()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Failed to create category')
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)}
        className="w-full border-2 border-dashed border-gray-200 rounded-xl py-3 text-sm text-gray-400 hover:border-indigo-400 hover:text-indigo-500 transition">
        + Add new category
      </button>
    )
  }

  return (
    <div className="bg-white border border-indigo-200 rounded-xl p-4 space-y-3">
      <p className="text-sm font-semibold text-gray-700">New Category</p>
      <div className="flex gap-3">
        <div>
          <p className="text-xs text-gray-500 mb-1">Icon</p>
          <div className="flex flex-wrap gap-1 w-48">
            {PRESET_ICONS.map(i => (
              <button key={i} onClick={() => setIcon(i)}
                className={`text-lg p-1 rounded ${icon === i ? 'bg-indigo-100 ring-2 ring-indigo-400' : 'hover:bg-gray-100'}`}>
                {i}
              </button>
            ))}
          </div>
        </div>
        <div className="flex-1 space-y-2">
          <div>
            <p className="text-xs text-gray-500 mb-1">Name</p>
            <input value={name} onChange={e => handleNameChange(e.target.value)} placeholder="e.g. Entertainment"
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Slug (auto-generated)</p>
            <input value={slug} onChange={e => setSlug(e.target.value)} placeholder="e.g. entertainment"
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm w-full font-mono focus:outline-none focus:ring-2 focus:ring-indigo-300" />
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Colour</p>
            <div className="flex gap-1.5 flex-wrap">
              {PRESET_COLOURS.map(c => (
                <button key={c} onClick={() => setColour(c)}
                  className={`w-6 h-6 rounded-full ${colour === c ? 'ring-2 ring-offset-1 ring-gray-500' : ''}`}
                  style={{ backgroundColor: c }} />
              ))}
              <input type="color" value={colour} onChange={e => setColour(e.target.value)}
                className="w-6 h-6 rounded cursor-pointer border-0" title="Custom colour" />
            </div>
          </div>
        </div>
      </div>
      {error && <p className="text-xs text-red-500">{error}</p>}
      <div className="flex justify-end gap-2">
        <button onClick={() => setOpen(false)} className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5">Cancel</button>
        <button onClick={handleAdd} disabled={saving || !name.trim()}
          className="text-sm bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition">
          {saving ? 'Adding...' : 'Add Category'}
        </button>
      </div>
    </div>
  )
}

export default function Categories() {
  const queryClient = useQueryClient()

  const { data: categories, isLoading } = useQuery({
    queryKey: ['categories'],
    queryFn: () => listCategories().then(r => r.data),
  })

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['categories'] })
    queryClient.invalidateQueries({ queryKey: ['transactions'] })
    queryClient.invalidateQueries({ queryKey: ['category-stats'] })
  }

  return (
    <div className="max-w-2xl mx-auto py-10 px-4">
      <h1 className="text-2xl font-bold text-gray-800 mb-1">Categories</h1>
      <p className="text-gray-500 text-sm mb-6">
        Manage spending categories. Changes reflect immediately in transactions and charts.
      </p>

      {isLoading && <p className="text-gray-400 text-sm">Loading...</p>}

      <ul className="space-y-2 mb-4">
        {categories?.map(cat => (
          <CategoryRow key={cat.id} cat={cat} onSaved={refresh} onDeleted={refresh} />
        ))}
      </ul>

      <AddCategoryForm onAdded={refresh} />
    </div>
  )
}
