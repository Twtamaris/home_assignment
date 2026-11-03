import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { Organisation, User, Conversation, Message, Citation, ProposalState } from '../types'
import { api, ApiError, authFetch, extractErrorMessage } from '../api'
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
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState<'customer' | 'admin'>(user.role === 'admin' ? 'admin' : 'customer')  // staff land in their analytics chat

  // Streaming
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingContent, setStreamingContent] = useState('')
  const [activeToolMessage, setActiveToolMessage] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  const streamedRef = useRef('')

  // Confirmation cards
  const [proposals, setProposals] = useState<Record<string, ProposalState>>({})
  const [busyProposalId, setBusyProposalId] = useState<string | null>(null)
  const requestedProposals = useRef<Set<string>>(new Set())
  const [panelRefresh, setPanelRefresh] = useState(0)

  // Panels
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const [isAdminModalOpen, setIsAdminModalOpen] = useState(false)
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null)
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  const activeConvRef = useRef<string | null>(null)
  activeConvRef.current = activeConvId

  // ---- conversations ------------------------------------------------------------------------------
  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api.listConversations(chatMode))
    } catch (err) {
      console.error(err)
    }
  }, [chatMode])

  const loadConversations = useCallback(async () => {
    try {
      const convs = await api.listConversations(chatMode)
      setConversations(convs)
      if (convs.length > 0) {
        setActiveConvId((current) => (current && convs.find((c) => c.id === current) ? current : convs[0].id))
      } else {
        const title = chatMode === 'admin' ? 'Analytics' : 'New Chat'
        const fresh = await api.createConversation(title, chatMode)
        setConversations([fresh])
        setActiveConvId(fresh.id)
      }
    } catch (err: any) {
      setLoadError(extractErrorMessage(err, 'Could not load your conversations.'))
    }
  }, [chatMode])

  useEffect(() => {
    loadConversations()
  }, [loadConversations, org.id])

  // ---- messages and the state of the cards in them --------------------------------------------------
  const hydrateProposals = useCallback((list: Message[]) => {
    const ids = list.map((m) => m.card?.proposal_id).filter((id): id is string => !!id && !requestedProposals.current.has(id))
    ids.forEach((id) => {
      requestedProposals.current.add(id)
      api.getProposal(id)
        .then((state) => setProposals((prev) => ({ ...prev, [id]: state })))
        .catch(() => setProposals((prev) => ({ ...prev, [id]: { status: 'failed' } })))
    })
  }, [])

  const loadMessages = useCallback(async (convId: string, quiet = false) => {
    if (!quiet) {
      setLoadingMessages(true)
      setLoadError(null)
    }
    try {
      const msgs = await api.getMessages(convId)
      if (activeConvRef.current !== convId) return
      setMessages(msgs)
      hydrateProposals(msgs)
    } catch (err: any) {
      if (!quiet) setLoadError(extractErrorMessage(err, 'Could not load this conversation.'))
    } finally {
      if (!quiet) setLoadingMessages(false)
    }
  }, [hydrateProposals])

  useEffect(() => {
    if (activeConvId) loadMessages(activeConvId)
    else setMessages([])
  }, [activeConvId, loadMessages])

  const markProposal = async (id: string) => {
    try {
      const state = await api.getProposal(id)
      setProposals((prev) => ({ ...prev, [id]: state }))
    } catch {
      /* the next reload will show it */
    }
  }

  // ---- sidebar actions -------------------------------------------------------------------------------
  const handleNewChat = async (mode: 'customer' | 'admin' = chatMode) => {
    try {
      const fresh = await api.createConversation(mode === 'admin' ? 'Analytics' : 'New Chat', mode)
      setConversations((prev) => [fresh, ...prev])
      setActiveConvId(fresh.id)
      setMessages([])
      setIsSidebarOpen(false)
    } catch (err) {
      console.error(err)
    }
  }

  const handleRenameChat = async (id: string, newTitle: string) => {
    try {
      const updated = await api.renameConversation(id, newTitle)
      setConversations((prev) => prev.map((c) => (c.id === id ? updated : c)))
    } catch (err) {
      console.error(err)
    }
  }

  const handleDeleteChat = async (id: string) => {
    try {
      await api.deleteConversation(id)
      const remaining = conversations.filter((c) => c.id !== id)
      setConversations(remaining)
      if (activeConvId === id) setActiveConvId(remaining.length > 0 ? remaining[0].id : null)
      if (remaining.length === 0) loadConversations()
    } catch (err) {
      console.error(err)
    }
  }

  const handleToggleChatMode = (mode: 'customer' | 'admin') => {
    setChatMode(mode)
    setActiveConvId(null)
    setMessages([])
  }

  // ---- streaming a reply ------------------------------------------------------------------------------
  const handleSendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) return

    let convId = activeConvId
    if (!convId) {
      const fresh = await api.createConversation('New Chat', chatMode)
      setConversations((prev) => [fresh, ...prev])
      setActiveConvId(fresh.id)
      activeConvRef.current = fresh.id
      convId = fresh.id
    }
    const thisConv = convId

    setMessages((prev) => [...prev, { id: `client_${Date.now()}`, conversation_id: thisConv, sender: 'user', content: text, created_at: new Date().toISOString() }])
    setIsStreaming(true)
    setStreamingContent('')
    setActiveToolMessage(null)
    streamedRef.current = ''

    const controller = new AbortController()
    abortControllerRef.current = controller
    let aborted = false

    try {
      const response = await authFetch(`/chat/conversations/${thisConv}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text }),
        signal: controller.signal,
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: `Request failed (${response.status})` }))
        throw new Error(extractErrorMessage(err, `Request failed (${response.status})`))
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) {
          const event = block.match(/^event:\s*(\w+)/m)?.[1]
          const data = block.match(/^data:\s*(.*)/m)?.[1]
          if (!event || data === undefined) continue
          let payload: any = {}
          try { payload = JSON.parse(data) } catch { payload = {} }
          if (event === 'tool_start') setActiveToolMessage(payload.message || 'Working...')
          else if (event === 'tool_end') setActiveToolMessage(null)
          else if (event === 'reset') {
            streamedRef.current = ''
            setStreamingContent('')
          } else if (event === 'token') {
            streamedRef.current += payload.token
            setStreamingContent(streamedRef.current)
          }
        }
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        aborted = true
      } else if (activeConvRef.current === thisConv) {
        setMessages((prev) => [...prev, { id: `err_${Date.now()}`, conversation_id: thisConv, sender: 'system', content: err.message || 'Something went wrong.', created_at: new Date().toISOString() }])
      }
    } finally {
      setIsStreaming(false)
      setStreamingContent('')
      setActiveToolMessage(null)
      abortControllerRef.current = null
    }

    if (!aborted) {
      // The server saved the reply, its card and its citations. Show exactly what was saved, then pick up a new title.
      await loadMessages(thisConv, true)
      refreshConversations()
    }
  }

  const handleStopStreaming = () => {
    const partial = streamedRef.current
    abortControllerRef.current?.abort()
    setIsStreaming(false)
    setStreamingContent('')
    setActiveToolMessage(null)
    if (partial && activeConvRef.current) {
      setMessages((prev) => [...prev, { id: `stopped_${Date.now()}`, conversation_id: activeConvRef.current as string, sender: 'agent', content: `${partial}\n\n*(stopped)*`, created_at: new Date().toISOString() }])
    }
  }

  // ---- confirmation cards ---------------------------------------------------------------------------------
  const settle = async (proposalId: string) => {
    await markProposal(proposalId)
    if (activeConvRef.current) await loadMessages(activeConvRef.current, true)
    setPanelRefresh((n) => n + 1)
  }

  const handleConfirmProposal = async (proposalId: string) => {
    setBusyProposalId(proposalId)
    try {
      await api.confirmProposal(proposalId)
    } catch (err: any) {
      // A 409 means the world changed (slot taken, stock gone). The server already wrote the explanation into the thread.
      if (!(err instanceof ApiError && err.status === 409) && activeConvRef.current) {
        setMessages((prev) => [...prev, { id: `confirm_err_${Date.now()}`, conversation_id: activeConvRef.current as string, sender: 'system', content: err.message || 'Could not confirm.', created_at: new Date().toISOString() }])
      }
    } finally {
      await settle(proposalId)
      setBusyProposalId(null)
    }
  }

  const handleRejectProposal = async (proposalId: string) => {
    setBusyProposalId(proposalId)
    try {
      await api.rejectProposal(proposalId)
    } catch (err: any) {
      if (activeConvRef.current) {
        setMessages((prev) => [...prev, { id: `reject_err_${Date.now()}`, conversation_id: activeConvRef.current as string, sender: 'system', content: err.message || 'Could not discard.', created_at: new Date().toISOString() }])
      }
    } finally {
      await settle(proposalId)
      setBusyProposalId(null)
    }
  }

  return (
    <div className="flex flex-col h-dvh bg-slate-950 text-slate-100 overflow-hidden font-sans">
      <Navbar
        org={org}
        user={user}
        onOpenDrawer={() => setIsDrawerOpen(true)}
        onOpenAdminModal={() => setIsAdminModalOpen(true)}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        onLogout={() => logout()}
      />

      <div className="flex-1 flex overflow-hidden min-h-0">
        <Sidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          conversations={conversations}
          activeConvId={activeConvId}
          onSelectConversation={(id) => { setActiveConvId(id); setIsSidebarOpen(false) }}
          onNewChat={handleNewChat}
          onRenameChat={handleRenameChat}
          onDeleteChat={handleDeleteChat}
          user={user}
          org={org}
          chatMode={chatMode}
          onToggleChatMode={handleToggleChatMode}
        />

        <MessageThread
          messages={messages}
          streamingContent={streamingContent}
          activeToolMessage={activeToolMessage}
          isStreaming={isStreaming}
          loading={loadingMessages}
          loadError={loadError}
          onRetryLoad={() => (activeConvId ? loadMessages(activeConvId) : loadConversations())}
          proposals={proposals}
          busyProposalId={busyProposalId}
          onSendMessage={handleSendMessage}
          onConfirmProposal={handleConfirmProposal}
          onRejectProposal={handleRejectProposal}
          onStopStreaming={handleStopStreaming}
          onSelectCitation={setSelectedCitation}
          org={org}
          chatMode={chatMode}
        />
      </div>

      <CustomerDrawer isOpen={isDrawerOpen} onClose={() => setIsDrawerOpen(false)} user={user} org={org} refreshKey={panelRefresh} />
      <CitationModal citation={selectedCitation} onClose={() => setSelectedCitation(null)} />
      <AdminAnalyticsModal isOpen={isAdminModalOpen} onClose={() => setIsAdminModalOpen(false)} org={org} />
    </div>
  )
}
