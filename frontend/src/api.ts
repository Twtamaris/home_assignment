import { Organisation, User, Conversation, Message, Order, Booking } from './types'

const API_BASE = '/api'

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export const api = {
  // --- Auth ---
  async login(payload: { email: string; password: string; org_id?: string }): Promise<{ access_token: string; user: User }> {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Login failed' }))
      throw new Error(err.detail || 'Login failed')
    }
    return res.json()
  },

  async register(payload: { email: string; password: string; name: string; org_id: string; role?: string }): Promise<{ access_token: string; user: User }> {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Registration failed' }))
      throw new Error(err.detail || 'Registration failed')
    }
    return res.json()
  },

  async getMe(): Promise<User> {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Not authenticated')
    return res.json()
  },

  // --- Organisations ---
  async getOrganisations(): Promise<Organisation[]> {
    const res = await fetch(`${API_BASE}/orgs`)
    if (!res.ok) throw new Error('Failed to load organisations')
    return res.json()
  },

  async getOrganisation(slugOrId: string): Promise<Organisation> {
    const res = await fetch(`${API_BASE}/orgs/${slugOrId}`)
    if (!res.ok) throw new Error('Organisation not found')
    return res.json()
  },

  // --- Conversations ---
  async listConversations(agentType = 'customer'): Promise<Conversation[]> {
    const res = await fetch(`${API_BASE}/chat/conversations?agent_type=${agentType}`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load chats')
    return res.json()
  },

  async createConversation(title = 'New Chat', agentType = 'customer'): Promise<Conversation> {
    const res = await fetch(`${API_BASE}/chat/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify({ title, agent_type: agentType }),
    })
    if (!res.ok) throw new Error('Failed to create chat')
    return res.json()
  },

  async renameConversation(convId: string, title: string): Promise<Conversation> {
    const res = await fetch(`${API_BASE}/chat/conversations/${convId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify({ title }),
    })
    if (!res.ok) throw new Error('Failed to rename chat')
    return res.json()
  },

  async deleteConversation(convId: string): Promise<void> {
    const res = await fetch(`${API_BASE}/chat/conversations/${convId}`, {
      method: 'DELETE',
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to delete chat')
  },

  async getMessages(convId: string): Promise<Message[]> {
    const res = await fetch(`${API_BASE}/chat/conversations/${convId}/messages`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load messages')
    return res.json()
  },

  // --- Orders & Bookings ---
  async listOrders(): Promise<Order[]> {
    const res = await fetch(`${API_BASE}/orders`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) return []
    return res.json()
  },

  async listBookings(): Promise<Booking[]> {
    const res = await fetch(`${API_BASE}/bookings`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) return []
    return res.json()
  },

  async advanceOrderStatus(orderId: string, newStatus: string): Promise<Order> {
    const res = await fetch(`${API_BASE}/admin/orders/${orderId}/advance_status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...getAuthHeader() },
      body: JSON.stringify({ new_status: newStatus }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to advance status' }))
      throw new Error(err.detail)
    }
    return res.json()
  },

  async getAdminActivitySummary(): Promise<any> {
    const res = await fetch(`${API_BASE}/admin/activity_summary`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load activity summary')
    return res.json()
  },

  async getAdminClientsToday(): Promise<any> {
    const res = await fetch(`${API_BASE}/admin/clients_today`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load clients data')
    return res.json()
  },

  async getAdminConversionRate(): Promise<any> {
    const res = await fetch(`${API_BASE}/admin/conversion_rate`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load conversion rate')
    return res.json()
  },

  async getAdminTopItems(): Promise<any> {
    const res = await fetch(`${API_BASE}/admin/top_items`, {
      headers: { ...getAuthHeader() },
    })
    if (!res.ok) throw new Error('Failed to load top items')
    return res.json()
  },
}

