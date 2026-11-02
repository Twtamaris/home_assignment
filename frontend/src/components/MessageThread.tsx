import React, { useState, useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Send, Square, Sparkles, BookOpen, Loader2, Bot, User as UserIcon } from 'lucide-react'
import { Message, Citation, Organisation } from '../types'
import { RichCard } from './RichCards'

interface MessageThreadProps {
  messages: Message[]
  streamingContent: string
  activeToolMessage: string | null
  isStreaming: boolean
  onSendMessage: (text: string) => void
  onStopStreaming: () => void
  onSelectCitation: (citation: Citation) => void
  org: Organisation
  chatMode: 'customer' | 'admin'
}

export const MessageThread: React.FC<MessageThreadProps> = ({
  messages,
  streamingContent,
  activeToolMessage,
  isStreaming,
  onSendMessage,
  onStopStreaming,
  onSelectCitation,
  org,
  chatMode,
}) => {
  const [inputText, setInputText] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, activeToolMessage])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submitMessage()
    }
  }

  const submitMessage = () => {
    if (!inputText.trim() || isStreaming) return
    onSendMessage(inputText.trim())
    setInputText('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleTextareaInput = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputText(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`
  }

  const handleCardAction = (actionText: string) => {
    onSendMessage(actionText)
  }

  return (
    <div className="flex-1 flex flex-col h-full bg-slate-950 overflow-hidden relative">
      {/* Scrollable Messages Container */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {messages.length === 0 && !isStreaming && (
          <div className="max-w-md mx-auto text-center py-16 space-y-4">
            <div
              className="w-14 h-14 rounded-2xl mx-auto flex items-center justify-center text-white shadow-xl"
              style={{
                background: `linear-gradient(135deg, ${org.primary_color}, ${org.secondary_color})`,
              }}
            >
              <Bot className="w-8 h-8" />
            </div>
            <div>
              <h3 className="text-base font-bold text-white">
                {chatMode === 'admin' ? 'Admin Analytics Agent' : org.agent_name}
              </h3>
              <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto leading-relaxed">
                {chatMode === 'admin'
                  ? 'Ask operational metrics: "How did we do today?", "What is our conversion rate?", or "Which items sell most?"'
                  : org.greeting || 'Namaste! How may I assist you today?'}
              </p>
            </div>
          </div>
        )}

        {messages.map((m) => {
          const isUser = m.sender === 'user'

          return (
            <div
              key={m.id}
              className={`flex gap-3 max-w-3xl mx-auto ${isUser ? 'justify-end' : 'justify-start'}`}
            >
              {!isUser && (
                <div
                  className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-white text-xs font-bold shadow-md mt-1"
                  style={{
                    backgroundColor: chatMode === 'admin' ? '#7e22ce' : org.primary_color,
                  }}
                >
                  <Bot className="w-4 h-4" />
                </div>
              )}

              <div className={`space-y-2 max-w-[85%] sm:max-w-[75%]`}>
                {/* Message Bubble */}
                <div
                  className={`p-4 rounded-2xl text-xs sm:text-sm leading-relaxed shadow-md ${
                    isUser
                      ? 'bg-slate-800 text-white border border-slate-700/80 rounded-tr-xs'
                      : 'bg-slate-900/90 text-slate-200 border border-slate-800 rounded-tl-xs'
                  }`}
                >
                  <div className="prose prose-invert prose-xs sm:prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  </div>

                  {/* Inline Rich Card */}
                  {m.card && <RichCard card={m.card} onAction={handleCardAction} />}

                  {/* Clickable Citation Chips */}
                  {m.citations && m.citations.length > 0 && (
                    <div className="mt-3 pt-2.5 border-t border-slate-800 flex flex-wrap gap-1.5">
                      {m.citations.map((c, i) => (
                        <button
                          key={i}
                          onClick={() => onSelectCitation(c)}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium bg-amber-500/10 hover:bg-amber-500/20 text-amber-300 border border-amber-500/25 transition active:scale-95"
                          title="Click to view verified source excerpt"
                        >
                          <BookOpen className="w-3 h-3 text-amber-400 shrink-0" />
                          <span className="truncate max-w-[200px]">{c.section}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {isUser && (
                <div className="w-8 h-8 rounded-xl shrink-0 bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300 text-xs mt-1">
                  <UserIcon className="w-4 h-4" />
                </div>
              )}
            </div>
          )
        })}

        {/* Live Streaming Indicator & Active Tool Execution */}
        {isStreaming && (
          <div className="flex gap-3 max-w-3xl mx-auto justify-start">
            <div
              className="w-8 h-8 rounded-xl shrink-0 flex items-center justify-center text-white text-xs font-bold shadow-md mt-1 animate-pulse"
              style={{
                backgroundColor: chatMode === 'admin' ? '#7e22ce' : org.primary_color,
              }}
            >
              <Bot className="w-4 h-4" />
            </div>

            <div className="space-y-2 max-w-[85%] sm:max-w-[75%]">
              {/* Visible Tool Activity Pill */}
              {activeToolMessage && (
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-500/30 animate-pulse">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-emerald-400" />
                  <span>{activeToolMessage}</span>
                </div>
              )}

              {/* Incremental Streamed Text */}
              {streamingContent && (
                <div className="p-4 rounded-2xl text-xs sm:text-sm leading-relaxed shadow-md bg-slate-900/90 text-slate-200 border border-slate-800 rounded-tl-xs">
                  <div className="prose prose-invert prose-xs sm:prose-sm max-w-none">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{streamingContent}</ReactMarkdown>
                  </div>
                  <span className="inline-block w-1.5 h-4 ml-1 bg-emerald-400 animate-pulse align-middle" />
                </div>
              )}
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Floating Stop Button if Streaming */}
      {isStreaming && (
        <div className="absolute bottom-24 left-1/2 -translate-x-1/2 z-20">
          <button
            onClick={onStopStreaming}
            className="flex items-center gap-2 px-4 py-2 rounded-full text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-white shadow-xl shadow-rose-950/60 transition active:scale-95"
          >
            <Square className="w-3 h-3 fill-current" />
            <span>Stop Response</span>
          </button>
        </div>
      )}

      {/* Message Input Footer */}
      <div className="p-4 border-t border-slate-800 bg-slate-900/80 backdrop-blur-md">
        <div className="max-w-3xl mx-auto flex items-end gap-2 bg-slate-950 border border-slate-800 rounded-2xl p-2 focus-within:border-emerald-500/50 focus-within:ring-1 focus-within:ring-emerald-500/20 transition">
          <textarea
            ref={textareaRef}
            rows={1}
            value={inputText}
            onChange={handleTextareaInput}
            onKeyDown={handleKeyDown}
            placeholder={
              chatMode === 'admin'
                ? 'Ask about revenue, new customers, conversion, or top items...'
                : `Ask ${org.agent_name} about products, bookings, reorders, or policies...`
            }
            className="flex-1 bg-transparent text-xs sm:text-sm text-slate-200 placeholder-slate-500 resize-none outline-hidden px-2 py-1 max-h-36"
          />

          <button
            onClick={submitMessage}
            disabled={!inputText.trim() || isStreaming}
            className="p-2.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:hover:bg-emerald-600 text-white transition active:scale-95 shrink-0"
            title="Send (Enter)"
          >
            <Send className="w-4 h-4" />
          </button>
        </div>
        <div className="max-w-3xl mx-auto flex justify-between items-center px-2 mt-1.5 text-[10px] text-slate-500">
          <span>Enter to send, Shift + Enter for new line</span>
          <span>{chatMode === 'admin' ? 'Admin Scoped Session' : `${org.name} Agent`}</span>
        </div>
      </div>
    </div>
  )
}

