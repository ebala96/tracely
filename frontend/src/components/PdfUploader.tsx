import { useCallback, useState } from 'react'
import { useDropzone } from 'react-dropzone'
import { uploadStatement, getStatement, type Statement, type UploadResponse } from '../api/client'

type UploadStatus = 'idle' | 'uploading' | 'processing' | 'done' | 'failed'

interface FileUpload {
  file: File
  status: UploadStatus
  statement?: Statement
  error?: string
}

interface Props {
  onDone?: (statement: Statement) => void
}

export default function PdfUploader({ onDone }: Props) {
  const [uploads, setUploads] = useState<FileUpload[]>([])

  const processFile = async (file: File) => {
    setUploads(prev => [...prev, { file, status: 'uploading' }])

    try {
      const { data: upload } = await uploadStatement(file)
      setUploads(prev =>
        prev.map(u => u.file === file ? { ...u, status: 'processing' } : u)
      )
      pollStatus(file, upload.statement_id)
    } catch {
      setUploads(prev =>
        prev.map(u => u.file === file ? { ...u, status: 'failed', error: 'Upload failed' } : u)
      )
    }
  }

  const pollStatus = (file: File, id: string) => {
    const interval = setInterval(async () => {
      try {
        const { data } = await getStatement(id)
        if (data.status === 'done') {
          clearInterval(interval)
          setUploads(prev =>
            prev.map(u => u.file === file ? { ...u, status: 'done', statement: data } : u)
          )
          onDone?.(data)
        } else if (data.status === 'failed') {
          clearInterval(interval)
          setUploads(prev =>
            prev.map(u =>
              u.file === file ? { ...u, status: 'failed', error: data.error_msg ?? 'Processing failed' } : u
            )
          )
        }
      } catch {
        clearInterval(interval)
      }
    }, 3000)
  }

  const onDrop = useCallback((accepted: File[]) => {
    accepted.forEach(processFile)
  }, [])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { 'application/pdf': ['.pdf'] },
    multiple: true,
  })

  const statusLabel: Record<UploadStatus, string> = {
    idle: '',
    uploading: 'Uploading...',
    processing: 'Parsing & embedding...',
    done: 'Done',
    failed: 'Failed',
  }

  const statusColor: Record<UploadStatus, string> = {
    idle: '',
    uploading: 'text-blue-500',
    processing: 'text-yellow-500',
    done: 'text-green-500',
    failed: 'text-red-500',
  }

  return (
    <div className="space-y-4">
      <div
        {...getRootProps()}
        className={`border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors
          ${isDragActive ? 'border-indigo-500 bg-indigo-50' : 'border-gray-300 hover:border-indigo-400 hover:bg-gray-50'}`}
      >
        <input {...getInputProps()} />
        <div className="text-4xl mb-3">📄</div>
        {isDragActive
          ? <p className="text-indigo-600 font-medium">Drop your PDFs here</p>
          : <p className="text-gray-500">Drag & drop bank statement PDFs, or <span className="text-indigo-600 underline">click to browse</span></p>
        }
        <p className="text-xs text-gray-400 mt-1">Supports multiple files</p>
      </div>

      {uploads.length > 0 && (
        <ul className="space-y-2">
          {uploads.map((u, i) => (
            <li key={i} className="flex items-center justify-between bg-white border border-gray-200 rounded-lg px-4 py-3">
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-lg">📋</span>
                <span className="text-sm font-medium text-gray-700 truncate">{u.file.name}</span>
              </div>
              <div className="text-right ml-4">
                <span className={`text-xs font-semibold ${statusColor[u.status]}`}>
                  {u.error ?? statusLabel[u.status]}
                </span>
                {u.status === 'processing' && (
                  <div className="w-4 h-4 border-2 border-yellow-400 border-t-transparent rounded-full animate-spin inline-block ml-2" />
                )}
                {u.status === 'done' && <span className="ml-2">✅</span>}
                {u.status === 'failed' && <span className="ml-2">❌</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
