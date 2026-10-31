import React, { useState } from 'react'
import { Plus, MessageSquare, Trash2, Edit2, Check, X, Shield, Sparkles } from 'lucide-react'
import { Conversation, User, Organisation } from '../types'

interface SidebarProps {
  isOpen: boolean
  onClose: () => void
  conversations: Conversation[]
  activeConvId: string | null
  onSelectConversation: (id: string) => void
  onNewChat: (agentType?: 'customer' | 'admin') => void
  onRenameChat: (id: string, newTitle: string) => void
  onDeleteChat: (id: string) => void
  user: User
  org: Organisation
  chatMode: 'customer' | 'admin'
  onToggleChatMode: (mode: 'customer' | 'admin') => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onClose,
  conversations,
  activeConvId,
  onSelectConversation,
  onNewChat,
  onRenameChat,
  onDeleteChat,
  user,
  org,
  chatMode,
  onToggleChatMode,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editTitle, setEditTitle] = useState('')

  const startEditing = (conv: Conversation, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(conv.id)
    setEditTitle(conv.title)
  }

  const saveEditing = (id: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (editTitle.trim()) {
      onRenameChat(id, editTitle.trim())
    }
    setEditingId(null)
  }

  const cancelEditing = (e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingId(null)
  }

  return (
    <>
      {/* Mobile Backdrop */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-xs lg:hidden"
        />
      )}

      <aside
        className={`fixed lg:static inset-y-0 left-0 z-40 w-72 bg-slate-950 border-r border-slate-800/80 flex flex-col transition-transform duration-200 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        {/* New Chat Button */}
        <div className="p-3 border-b border-slate-800/80 space-y-2">
          {user.role === 'admin' && (
            <div className="grid grid-cols-2 p-1 rounded-xl bg-slate-900 border border-slate-800 text-[11px] font-semibold">
              <button
                onClick={() => onToggleChatMode('customer')}
                className={`py-1.5 rounded-lg transition ${
                  chatMode === 'customer'
                    ? 'bg-slate-800 text-white shadow-xs'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                Store Chat
              </button>
              <button
                onClick={() => onToggleChatMode('admin')}
                className={`py-1.5 rounded-lg flex items-center justify-center gap-1 transition ${
                  chatMode === 'admin'
                    ? 'bg-purple-900 text-purple-200 shadow-xs'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                <Shield className="w-3 h-3 text-purple-400" />
                <span>Admin Chat</span>
              </button>
            </div>
          )}

          <button
            onClick={() => onNewChat(chatMode)}
            className="w-full py-2.5 px-3 rounded-xl text-xs font-semibold bg-slate-900 hover:bg-slate-800 border border-slate-700/60 hover:border-slate-600 text-white transition flex items-center justify-center gap-2 active:scale-98 shadow-xs"
          >
            <Plus className="w-4 h-4 text-emerald-400" />
            <span>New {chatMode === 'admin' ? 'Analytics Inquiry' : 'Conversation'}</span>
          </button>
        </div>

        {/* Conversation List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {conversations.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-500">
              No conversations yet.
            </div>
          ) : (
            conversations.map((conv) => {
              const isActive = conv.id === activeConvId
              const isEditing = editingId === conv.id

              return (
                <div
                  key={conv.id}
                  onClick={() => onSelectConversation(conv.id)}
                  className={`group relative flex items-center justify-between px-3 py-2.5 rounded-xl text-xs cursor-pointer transition ${
                    isActive
                      ? 'bg-slate-800/90 text-white font-medium shadow-xs border border-slate-700/50'
                      : 'text-slate-400 hover:bg-slate-900/80 hover:text-slate-200'
                  }`}
                >
                  <div className="flex items-center gap-2.5 min-w-0 pr-2">
                    <MessageSquare
                      className={`w-3.5 h-3.5 shrink-0 ${
                        isActive ? 'text-emerald-400' : 'text-slate-500'
                      }`}
                    />
                    {isEditing ? (
                      <input
                        type="text"
                        value={editTitle}
                        onChange={(e) => setEditTitle(e.target.value)}
                        onClick={(e) => e.stopPropagation()}
                        className="bg-slate-900 text-white px-2 py-0.5 rounded text-xs outline-hidden ring-1 ring-emerald-500 w-full"
                        autoFocus
                      />
                    ) : (
                      <span className="truncate">{conv.title}</span>
                    )}
                  </div>

                  {/* Rename / Delete Actions */}
                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition shrink-0">
                    {isEditing ? (
                      <>
                        <button
                          onClick={(e) => saveEditing(conv.id, e)}
                          className="p-1 rounded text-emerald-400 hover:bg-slate-700"
                        >
                          <Check className="w-3.5 h-3.5" />
                        </button>
                        <button
                          onClick={cancelEditing}
                          className="p-1 rounded text-slate-400 hover:bg-slate-700"
                        >
                          <X className="w-3.5 h-3.5" />
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          onClick={(e) => startEditing(conv, e)}
                          className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-700"
                          title="Rename"
                        >
                          <Edit2 className="w-3 h-3" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            onDeleteChat(conv.id)
                          }}
                          className="p-1 rounded text-slate-400 hover:text-rose-400 hover:bg-slate-700"
                          title="Delete"
                        >
                          <Trash2 className="w-3 h-3" />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )
            })
          )}
        </div>

        {/* Sidebar Footer */}
        <div className="p-3 border-t border-slate-900 text-[11px] text-slate-500 text-center">
          Multi-Tenant Isolation Enforced
        </div>
      </aside>
    </>
  )
}
