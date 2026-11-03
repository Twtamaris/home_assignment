import { Organisation, User, Conversation, Message, Order, Booking, ProposalState, AdminOrder, AdminBooking } from './types'

const API_BASE = '/api'

const TOKEN_KEY = 'auth_token'

/**
 * Session handling: the server issues a signed token at login. It is kept in localStorage and sent as a
 * Bearer header on every call. A 401 on a call that carried a token means the session ended (expired or
 * signed out elsewhere), so the token is dropped and the app is told to return to the entry point.
 */
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* storage unavailable: the session lasts until the page closes */
  }
}

export function getAuthHeader(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** fetch with the session token, and one place that notices an ended session. */
export async function authFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init.headers as Record<string, string> | undefined), ...getAuthHeader() },
  })
  if (res.status === 401 && getToken()) {
    setToken(null)
    window.dispatchEvent(new Event('auth:expired'))
  }
  return res
}

/** An API failure that keeps the HTTP status, so callers can tell a conflict (409) from other errors. */
export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function failure(res: Response, fallback: string): Promise<ApiError> {
  const err = await res.json().catch(() => ({ detail: fallback }))
  return new ApiError(extractErrorMessage(err, fallback), res.status)
}

export function extractErrorMessage(err: any, fallback: string): string {
  if (!err) return fallback
  const detail = err.detail !== undefined ? err.detail : err.message !== undefined ? err.message : err
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((item: any) => {
        if (typeof item === 'string') return item
        if (item?.msg) return item.msg
        return JSON.stringify(item)
      })
      .join(', ')
  }
  if (typeof detail === 'object') {
    if (detail.msg) return detail.msg
    return JSON.stringify(detail)
  }
  return String(detail)
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
      throw new Error(extractErrorMessage(err, 'Login failed'))
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
      throw new Error(extractErrorMessage(err, 'Registration failed'))
    }
    return res.json()
  },

  async getMe(): Promise<User> {
    const res = await authFetch(`/auth/me`)
    if (!res.ok) throw new Error('Not authenticated')
    return res.json()
  },

  /** Ends the session on the server (the token stops working everywhere), then forgets it here. */
  async logout(): Promise<void> {
    try {
      await fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: { ...getAuthHeader() } })
    } catch {
      /* offline: the token is still dropped locally */
    }
    setToken(null)
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
    const res = await authFetch(`/chat/conversations?agent_type=${agentType}`)
    if (!res.ok) throw new Error('Failed to load chats')
    return res.json()
  },

  async createConversation(title = 'New Chat', agentType = 'customer'): Promise<Conversation> {
    const res = await authFetch(`/chat/conversations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, agent_type: agentType }),
    })
    if (!res.ok) throw new Error('Failed to create chat')
    return res.json()
  },

  async renameConversation(convId: string, title: string): Promise<Conversation> {
    const res = await authFetch(`/chat/conversations/${convId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title }),
    })
    if (!res.ok) throw new Error('Failed to rename chat')
    return res.json()
  },

  async deleteConversation(convId: string): Promise<void> {
    const res = await authFetch(`/chat/conversations/${convId}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('Failed to delete chat')
  },

  async getMessages(convId: string): Promise<Message[]> {
    const res = await authFetch(`/chat/conversations/${convId}/messages`)
    if (!res.ok) throw new Error('Failed to load messages')
    return res.json()
  },

  // --- Orders & Bookings ---
  async listOrders(): Promise<Order[]> {
    const res = await authFetch(`/orders`)
    if (!res.ok) return []
    return res.json()
  },

  async listBookings(): Promise<Booking[]> {
    const res = await authFetch(`/bookings`)
    if (!res.ok) return []
    return res.json()
  },

  async confirmProposal(proposalId: string): Promise<any> {
    const res = await authFetch(`/actions/proposals/${proposalId}/confirm`, { method: 'POST' })
    if (!res.ok) throw await failure(res, 'Confirmation failed')
    return res.json()
  },

  async rejectProposal(proposalId: string): Promise<any> {
    const res = await authFetch(`/actions/proposals/${proposalId}/reject`, { method: 'POST' })
    if (!res.ok) throw await failure(res, 'Could not reject the proposal')
    return res.json()
  },

  async advanceOrderStatus(orderId: string, newStatus: string): Promise<Order> {
    const res = await authFetch(`/admin/orders/${orderId}/advance_status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_status: newStatus }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to advance status' }))
      throw new Error(extractErrorMessage(err, 'Failed to advance status'))
    }
    return res.json()
  },

  async listAdminOrders(): Promise<AdminOrder[]> {
    const res = await authFetch('/admin/orders')
    if (!res.ok) throw await failure(res, 'Failed to load orders')
    return res.json()
  },

  async listAdminBookings(): Promise<AdminBooking[]> {
    const res = await authFetch('/admin/bookings')
    if (!res.ok) throw await failure(res, 'Failed to load bookings')
    return res.json()
  },

  async getProposal(proposalId: string): Promise<ProposalState> {
    const res = await authFetch(`/actions/proposals/${proposalId}`)
    if (!res.ok) throw await failure(res, 'Proposal not found')
    const body = await res.json()
    return { status: body.status, expires_at: body.expires_at }
  },

  async getAdminActivitySummary(): Promise<any> {
    const res = await authFetch(`/admin/activity_summary`)
    if (!res.ok) throw new Error('Failed to load activity summary')
    return res.json()
  },

  async getAdminClientsToday(): Promise<any> {
    const res = await authFetch(`/admin/clients_today`)
    if (!res.ok) throw new Error('Failed to load clients data')
    return res.json()
  },

  async getAdminConversionRate(): Promise<any> {
    const res = await authFetch(`/admin/conversion_rate`)
    if (!res.ok) throw new Error('Failed to load conversion rate')
    return res.json()
  },

  async getAdminTopItems(): Promise<any> {
    const res = await authFetch(`/admin/top_items`)
    if (!res.ok) throw new Error('Failed to load top items')
    return res.json()
  },
}

