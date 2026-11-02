export interface Organisation {
  id: string
  slug: string
  name: string
  tagline?: string
  primary_color: string
  secondary_color: string
  accent_color: string
  agent_name: string
  agent_role: string
  greeting?: string
}

export interface User {
  id: string
  org_id: string
  email: string
  name: string
  role: 'customer' | 'admin'
}

export interface Conversation {
  id: string
  org_id: string
  user_id: string
  title: string
  agent_type: 'customer' | 'admin'
  created_at: string
  updated_at: string
}

export interface Citation {
  doc: string
  section: string
  excerpt: string
}

export interface ToolCall {
  tool: string
  message?: string
  result?: any
  status?: string
}

export interface Message {
  id: string
  conversation_id: string
  sender: 'user' | 'agent' | 'system'
  content: string
  tool_calls?: ToolCall[]
  citations?: Citation[]
  card?: any
  created_at: string
}

export interface OrderItem {
  sku: string
  name: string
  unit_price: number
  quantity: number
  subtotal: number
}

export interface Order {
  id: string
  org_id: string
  user_id: string
  status: 'pending' | 'confirmed' | 'shipped' | 'delivered' | 'cancelled'
  items: OrderItem[]
  total_price: number
  shipping_address?: string
  created_at: string
  updated_at: string
}

export interface Booking {
  id: string
  org_id: string
  user_id: string
  service_id: string
  service_name?: string
  practitioner_id: string
  practitioner_name?: string
  start_time: string
  end_time: string
  formatted_time?: string
  status: 'confirmed' | 'rescheduled' | 'cancelled'
  cancellation_fee: number
  notes?: string
  created_at: string
}

