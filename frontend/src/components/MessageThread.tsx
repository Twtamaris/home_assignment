import React, { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, Square, BookOpen, Loader2, Bot, User as UserIcon, AlertTriangle } from 'lucide-react'
import { Message, Citation, Organisation, ProposalState } from '../types'
import { RichCard } from './RichCards'

interface MessageThreadProps {
  messages: Message[]
  streamingContent: string
  activeToolMessage: string | null
  isStreaming: boolean
  loading: boolean
  loadError: string | null
  onRetryLoad: () => void
  proposals: Record<string, ProposalState>
  busyProposalId: string | null
  onSendMessage: (text: string) => void
  onConfirmProposal: (proposalId: string) => void
  onRejectProposal: (proposalId: string) => void
  onStopStreaming: () => void
  onSelectCitation: (citation: Citation) => void
  org: Organisation
  chatMode: 'customer' | 'admin'
}

const STARTERS: Record<string, string[]> = {
  retail: ['What green teas do you have?', 'What is your return policy?', 'Same as last time', 'Show my orders'],
  studio: ['What services do you offer?', 'Show free slots for a massage next Tuesday afternoon', 'What is your cancellation policy?', 'Show my bookings'],
  admin: ['How did we do today?', 'How many new clients this week?', 'What is our conversion rate?', 'What are the top items?'],
}

/** Markdown with real styling: lists, headings, tables and code blocks all read properly in the dark theme. */
const Markdown: React.FC<{ children: string }> = ({ children }) => (
  <div className="md-body">
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
        table: ({ node, ...props }) => <div className="md-table"><table {...props} /></div>,
      }}
    >
      {children}
    </ReactMarkdown>
  </div>
)

export const MessageThread: React.FC<MessageThreadProps> = ({
  messages, streamingContent, activeToolMessage, isStreaming, loading, loadError, onRetryLoad, proposals, busyProposalId,
  onSendMessage, onConfirmProposal, onRejectProposal, onStopStreaming, onSelectCitation, org, chatMode,
}) => {
  const [inputText, setInputText] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, streamingContent, activeToolMessage])

  const submitMessage = () => {
    if (!inputText.trim() || isStreaming) return
    onSendMessage(inputText.trim())
    setInputText('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter adds a line. Ignore Enter while an input method is composing text.
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submitMessage()
    }
  }

  const handleInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
  }

  const accent = chatMode === 'admin' ? '#7e22ce' : org.primary_color
  const starters = STARTERS[chatMode === 'admin' ? 'admin' : org.agent_kind] || []

  return (
    <div className="flex-1 min-w-0 flex flex-col h-full bg-slate-950 overflow-hidden relative">
      <div className="flex-1 overflow-y-auto px-3 sm:px-4 py-5 space-y-5" role="log" aria-live="polite" aria-label="Conversation">
        {loading && (
          <div className="flex items-center justify-center gap-2 py-16 text-xs text-slate-400" role="status">
            <Loader2 className="w-4 h-4 animate-spin" /> Loading conversation...
          </div>
        )}

        {!loading && loadError && (
          <div role="alert" className="max-w-md mx-auto text-center py-12 space-y-3">
            <AlertTriangle className="w-6 h-6 text-rose-400 mx-auto" />
            <p className="text-sm text-rose-300">{loadError}</p>
            <button onClick={onRetryLoad} className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs text-white">Try again</button>
          </div>
        )}

        {!loading && !loadError && messages.length === 0 && !isStreaming && (
          <div className="max-w-md mx-auto text-center py-10 space-y-4">
            <div className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center text-white shadow-xl"
                 style={{ background: `linear-gradient(135deg, ${org.primary_color}, ${org.secondary_color})` }}>
              <Bot className="w-8 h-8" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">{chatMode === 'admin' ? 'Admin analytics agent' : org.agent_name}</h2>
              <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto leading-relaxed">
                {chatMode === 'admin'
                  ? 'Read-only answers about your own organisation. Every number comes with its time window and definition.'
                  : org.greeting || 'Hello! How may I help you today?'}
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              {starters.map((s) => (
                <button key={s} onClick={() => onSendMessage(s)}
                  className="px-3 py-2 rounded-full text-[11px] bg-slate-900 hover:bg-slate-800 border border-slate-700 text-slate-300 transition">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {!loading && messages.map((m) => {
          const isUser = m.sender === 'user'
          const isSystem = m.sender === 'system'
          return (
            <div key={m.id} className={`flex gap-2.5 sm:gap-3 max-w-3xl mx-auto ${isUser ? 'justify-end' : 'justify-start'}`}>
              {!isUser && (
                <div className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-white shadow-md mt-1"
                     style={{ backgroundColor: isSystem ? '#9f1239' : accent }} aria-hidden>
                  {isSystem ? <AlertTriangle className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
                </div>
              )}

              <div className="min-w-0 max-w-[88%] sm:max-w-[78%]">
                <div className={`p-3.5 sm:p-4 rounded-2xl text-sm leading-relaxed shadow-md break-words ${
                  isUser ? 'bg-slate-800 text-white border border-slate-700/80 rounded-tr-sm'
                    : isSystem ? 'bg-rose-950/40 text-rose-200 border border-rose-500/30 rounded-tl-sm'
                    : 'bg-slate-900/90 text-slate-200 border border-slate-800 rounded-tl-sm'}`}>
                  <Markdown>{m.content}</Markdown>

                  {m.card && (
                    <RichCard
                      card={m.card}
                      proposal={m.card.proposal_id ? proposals[m.card.proposal_id] : undefined}
                      busy={!!m.card.proposal_id && busyProposalId === m.card.proposal_id}
                      onConfirm={onConfirmProposal}
                      onReject={onRejectProposal}
                      onAction={onSendMessage}
                    />
                  )}

                  {m.citations && m.citations.length > 0 && (
                    <div className="mt-3 pt-2.5 border-t border-slate-800 flex flex-wrap gap-1.5" aria-label="Sources">
                      {m.citations.map((c, i) => (
                        <button key={i} onClick={() => onSelectCitation(c)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-medium bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/25 transition active:scale-95 max-w-full"
                          title="View the source passage">
                          <BookOpen className="w-3 h-3 text-amber-400 shrink-0" />
                          <span className="truncate">{c.doc} › {c.section}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {isUser && (
                <div className="w-8 h-8 rounded-xl shrink-0 bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 mt-1" aria-hidden>
                  <UserIcon className="w-4 h-4" />
                </div>
              )}
            </div>
          )
        })}

        {/* Live tool activity and streamed text */}
        {isStreaming && (
          <div className="flex gap-2.5 sm:gap-3 max-w-3xl mx-auto justify-start">
            <div className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-white shadow-md mt-1 animate-pulse" style={{ backgroundColor: accent }} aria-hidden>
              <Bot className="w-4 h-4" />
            </div>
            <div className="space-y-2 min-w-0 max-w-[88%] sm:max-w-[78%]">
              {activeToolMessage && (
                <div role="status" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-500/30">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                  <span>{activeToolMessage}</span>
                </div>
              )}
              {streamingContent && (
                <div className="p-3.5 sm:p-4 rounded-2xl text-sm leading-relaxed shadow-md bg-slate-900/90 text-slate-200 border border-slate-800 rounded-tl-sm break-words">
                  <Markdown>{streamingContent}</Markdown>
                  <span className="inline-block w-1.5 h-4 ml-1 bg-emerald-400 animate-pulse align-middle" aria-hidden />
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {isStreaming && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-20">
          <button onClick={onStopStreaming}
            className="flex items-center gap-2 px-4 py-2.5 rounded-full text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white shadow-xl shadow-rose-950/60 transition active:scale-95">
            <Square className="w-3 h-3 fill-current" />
            <span>Stop</span>
          </button>
        </div>
      )}

      <div className="p-3 sm:p-4 border-t border-slate-800 bg-slate-900/80 backdrop-blur-md">
        <div className="max-w-3xl mx-auto flex items-end gap-2 bg-slate-950 border border-slate-800 rounded-2xl p-2 focus-within:border-emerald-500/50 focus-within:ring-1 focus-within:ring-emerald-500/20 transition">
          <textarea
            ref={textareaRef} rows={1} value={inputText} onChange={handleInput} onKeyDown={handleKeyDown}
            aria-label="Message"
            placeholder={chatMode === 'admin' ? 'Ask about revenue, clients, conversion, top items...' : `Message ${org.agent_name}...`}
            className="flex-1 min-w-0 bg-transparent text-sm text-slate-200 placeholder-slate-500 resize-none outline-hidden px-2 py-1.5 max-h-40"
          />
          <button onClick={submitMessage} disabled={!inputText.trim() || isStreaming} aria-label="Send message"
            className="p-2.5 rounded-xl text-white transition active:scale-95 shrink-0 disabled:opacity-40"
            style={{ backgroundColor: org.primary_color }}>
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="max-w-3xl mx-auto flex justify-between items-center px-2 mt-1.5 text-[10px] text-slate-500">
          <span>Enter to send · Shift+Enter for a new line</span>
          <span className="truncate ml-2">{chatMode === 'admin' ? 'Admin session (read-only)' : org.name}</span>
        </div>
      </div>
    </div>
  )
}
