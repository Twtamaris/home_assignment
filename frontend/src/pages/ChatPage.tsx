import React, { useState, useEffect, useRef } from 'react'
import { useAuth } from '../context/AuthContext'
import { Organisation, User, Conversation, Message, Citation } from '../types'
import { api } from '../api'
import { Navbar } from '../components/Navbar'
import { Sidebar } from '../components/Sidebar'
import { MessageThread } from '../components/MessageThread'
import { CustomerDrawer } from '../components/CustomerDrawer'
import { CitationModal } from '../components/CitationModal'
import { AdminAnalyticsModal } from '../components/AdminAnalyticsModal'

interface ChatPageProps {
  user: User
  org: Organisation
}

export const ChatPage: React.FC<ChatPageProps> = ({ user, org }) => {
  const { logout } = useAuth()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [chatMode, setChatMode] = useState<'customer' | 'admin'>('customer')

  // Streaming State
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [activeToolMessage, setActiveToolMessage] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  // Modals & Drawers
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  useEffect(() => {
    loadConversations()
  }, [chatMode, org.id])

  useEffect(() => {
    if (activeConvId) {
      loadMessages(activeConvId)
    } else {
      setMessages([])
    }
  }, [activeConvId])

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations(chatMode)
      setConversations(convs)
      if (convs.length > 0) {
        if (!activeConvId || !convs.find((c) => c.id === activeConvId)) {
          setActiveConvId(convs[0].id)
        }
      } else {
        // Automatically create a default conversation
        const title = chatMode === 'admin' ? 'Store Performance Review' : 'New Inquiries'
        const newConv = await api.createConversation(title, chatMode)
        setConversations([newConv])
        setActiveConvId(newConv.id)
      }
    } catch (err) {
      console.error(err)
    }
  }

  const loadMessages = async (convId: string) => {
    try {
      const msgs = await api.getMessages(convId)
      setMessages(msgs)
    } catch (err) {
      console.error(err)
    }
  }

  const handleNewChat = async (mode: 'customer' | 'admin' = chatMode) => {
    try {
      const title = mode === 'admin' ? 'New Analytics Inquiry' : 'New Conversation'
      const newConv = await api.createConversation(title, mode)
      setConversations([newConv, ...conversations])
      setActiveConvId(newConv.id)
      setMessages([])
      setIsSidebarOpen(false)
    } catch (err) {
      console.error(err)
    }
  }

  const handleRenameChat = async (id: string, newTitle: string) => {
    try {
      const updated = await api.renameConversation(id, newTitle)
      setConversations(conversations.map((c) => (c.id === id ? updated : c)))
    } catch (err) {
      console.error(err)
    }
  }

  const handleDeleteChat = async (id: string) => {
    try {
      await api.deleteConversation(id)
      const remaining = conversations.filter((c) => c.id !== id)
      setConversations(remaining)
      if (activeConvId === id) {
        setActiveConvId(remaining.length > 0 ? remaining[0].id : null)
      }
    } catch (err) {
      console.error(err)
    }
  }

  const handleToggleChatMode = (mode: 'customer' | 'admin') => {
    setChatMode(mode)
    setActiveConvId(null)
  }

  // --- Real-time SSE Chat Streaming ---
  const handleSendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) return

    let currentConvId = activeConvId
    if (!currentConvId) {
      const newConv = await api.createConversation('New Chat', chatMode)
      setConversations([newConv, ...conversations])
      setActiveConvId(newConv.id)
      currentConvId = newConv.id
    }

    // Append optimistic user message
    const userMsg: Message = {
      id: `client_${Date.now()}`,
      conversation_id: currentConvId,
      sender: 'user',
      content: text,
      created_at: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, userMsg])

    // Prepare streaming
    setIsStreaming(true)
    setStreamingContent('')
    setActiveToolMessage(null)

    const controller = new AbortController()
    abortControllerRef.current = controller

    const token = localStorage.getItem('auth_token')
    let streamText = ''
    let receivedCard: any = null
    let receivedCitations: Citation[] = []
    let receivedTools: any[] = []

    try {
      const response = await fetch(`/api/chat/conversations/${currentConvId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content: text }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(err.detail || `Server returned ${response.status}`)
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      if (reader) {
        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n\n')
          buffer = lines.pop() || ''

          for (const block of lines) {
            const trimmed = block.trim()
            if (!trimmed) continue

            const eventMatch = trimmed.match(/^event:\s*(\w+)/m)
            const dataMatch = trimmed.match(/^data:\s*(.*)/m)

            if (!eventMatch || !dataMatch) continue
            const eventType = eventMatch[1]
            let payload: any = {}
            try {
              payload = JSON.parse(dataMatch[1])
            } catch {
              payload = dataMatch[1]
            }

            if (eventType === 'tool_start') {
              setActiveToolMessage(payload.message || 'Executing tool...')
              receivedTools.push({ tool: payload.tool, status: 'running' })
            } else if (eventType === 'tool_end') {
              setActiveToolMessage(null)
            } else if (eventType === 'token') {
              streamText += payload.token
              setStreamingContent((prev) => prev + payload.token)
            } else if (eventType === 'done') {
              if (payload.card) receivedCard = payload.card
              if (payload.citations) receivedCitations = payload.citations
              if (payload.content) streamText = payload.content
            }
          }
        }
      }

      // Add finalized agent message
      const agentMsg: Message = {
        id: `agent_${Date.now()}`,
        conversation_id: currentConvId,
        sender: 'agent',
        content: streamText,
        card: receivedCard,
        citations: receivedCitations,
        tool_calls: receivedTools,
        created_at: new Date().toISOString(),
      }
      setMessages((prev) => [...prev, agentMsg])
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        const errorMsg: Message = {
          id: `err_${Date.now()}`,
          conversation_id: currentConvId,
          sender: 'system',
          content: `⚠️ Error: ${err.message}`,
          created_at: new Date().toISOString(),
        }
        setMessages((prev) => [...prev, errorMsg])
      }
    } finally {
      setIsStreaming(false)
      setStreamingContent('')
      setActiveToolMessage(null)
      abortControllerRef.current = null
    }
  }

  const handleStopStreaming = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      setIsStreaming(false)
      if (streamingContent) {
        setMessages((prev) => [
          ...prev,
          {
            id: `stopped_${Date.now()}`,
            conversation_id: activeConvId || 'conv',
            sender: 'agent',
            content: `${streamingContent} *(Response stopped)*`,
            created_at: new Date().toISOString(),
          },
        ])
      }
      setStreamingContent('')
      setActiveToolMessage(null)
    }
  }

  return (
    <div className="flex flex-col h-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Top Navbar */}
      <Navbar
        org={org}
        user={user}
        onOpenDrawer={() => setIsDrawerOpen(true)}
        onOpenAdminModal={() => setIsAdminModalOpen(true)}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        onLogout={logout}
      />

      {/* Main Body */}
      <div className="flex-1 flex overflow-hidden">
        {/* Sidebar */}
        <Sidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          conversations={conversations}
          activeConvId={activeConvId}
          onSelectConversation={(id) => {
            setActiveConvId(id)
            setIsSidebarOpen(false)
          }}
          onNewChat={handleNewChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          user={user}
          org={org}
          chatMode={chatMode}
          onToggleChatMode={handleToggleChatMode}
        />

        {/* Chat Thread */}
        <MessageThread
          messages={messages}
          streamingContent={streamingContent}
          activeToolMessage={activeToolMessage}
          isStreaming={isStreaming}
          onSendMessage={handleSendMessage}
          onStopStreaming={handleStopStreaming}
          onSelectCitation={(citation) => setSelectedCitation(citation)}
          org={org}
          chatMode={chatMode}
        />
      </div>

      {/* Customer Drawer (Orders/Bookings) */}
      <CustomerDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        user={user}
        org={org}
      />

      {/* Citation Source Modal */}
      <CitationModal
        citation={selectedCitation}
        onClose={() => setSelectedCitation(null)}
      />

      {/* Admin Analytics Modal */}
      <AdminAnalyticsModal
        isOpen={isAdminModalOpen}
        onClose={() => setIsAdminModalOpen(false)}
        org={org}
      />
    </div>
  )
}
