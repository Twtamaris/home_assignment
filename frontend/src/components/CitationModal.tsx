import React from 'react'
import { X, BookOpen, FileText } from 'lucide-react'
import { Citation } from '../types'

interface CitationModalProps {
  citation: Citation | null
  onClose: () => void
}

export const CitationModal: React.FC<CitationModalProps> = ({ citation, onClose }) => {
  if (!citation) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in">
      <div className="relative w-full max-w-lg rounded-2xl bg-slate-900 border border-slate-700 p-6 shadow-2xl text-slate-100">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="p-2.5 rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
            <BookOpen className="w-5 h-5" />
          </div>
          <div>
            <h3 className="font-semibold text-base text-white">Knowledge Base Source</h3>
            <p className="text-xs text-slate-400">Verified document reference</p>
          </div>
        </div>

        <div className="space-y-3">
          <div className="bg-slate-800/60 rounded-xl p-3 border border-slate-700/60">
            <div className="flex items-center gap-2 text-xs font-mono text-amber-300/90 mb-1">
              <FileText className="w-3.5 h-3.5" />
              <span>{citation.doc}</span>
            </div>
            <p className="text-sm font-medium text-slate-200">{citation.section}</p>
          </div>

          <div className="bg-slate-950/60 rounded-xl p-4 border border-slate-800 text-sm text-slate-300 leading-relaxed max-h-60 overflow-y-auto">
            {citation.excerpt}
          </div>
        </div>

        <div className="mt-6 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-white transition"
          >
            Close Excerpt
          </button>
        </div>
      </div>
    </div>
  )
}
