from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
import datetime

# --- Auth ---
class UserLogin(BaseModel):
    email: EmailStr
    password: str
    org_id: Optional[str] = None  # Entrypoint can supply this or derive from host/path

class UserRegister(BaseModel):
    email: EmailStr
    password: str
    name: str
    org_id: str
    role: Optional[str] = "customer"

class UserOut(BaseModel):
    id: str
    org_id: str
    email: str
    name: str
    role: str
    created_at: datetime.datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

# --- Organisation ---
class OrgOut(BaseModel):
    id: str
    slug: str
    name: str
    tagline: Optional[str] = None
    primary_color: str
    secondary_color: str
    accent_color: str
    agent_name: str
    agent_role: str
    greeting: Optional[str] = None

    class Config:
        from_attributes = True

# --- Products & Orders ---
class ProductOut(BaseModel):
    id: int
    org_id: str
    sku: str
    name: str
    category: str
    price: float
    stock: int
    description: Optional[str] = None

    class Config:
        from_attributes = True

class OrderItem(BaseModel):
    sku: str
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItem]
    shipping_address: Optional[str] = "Kathmandu, Nepal"

class OrderUpdate(BaseModel):
    items: Optional[List[OrderItem]] = None
    shipping_address: Optional[str] = None

class OrderOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    status: str
    items: List[Dict[str, Any]]
    total_price: float
    shipping_address: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

# --- Services & Bookings ---
class ServiceOut(BaseModel):
    id: str
    org_id: str
    name: str
    duration_minutes: int
    price: float
    description: Optional[str] = None

    class Config:
        from_attributes = True

class PractitionerOut(BaseModel):
    id: str
    org_id: str
    name: str
    title: str
    specialties: List[str]
    bio: Optional[str] = None

    class Config:
        from_attributes = True

class BookingCreate(BaseModel):
    service_id: str
    practitioner_id: str
    start_time: str  # ISO string in Asia/Kathmandu
    notes: Optional[str] = None

class BookingReschedule(BaseModel):
    new_start_time: str  # ISO string

class BookingOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    service_id: str
    practitioner_id: str
    start_time: datetime.datetime
    end_time: datetime.datetime
    status: str
    cancellation_fee: float
    reschedule_count: int
    notes: Optional[str] = None
    service_name: Optional[str] = None
    practitioner_name: Optional[str] = None
    created_at: datetime.datetime

    class Config:
        from_attributes = True

# --- Chat & Conversations ---
class ConversationCreate(BaseModel):
    title: Optional[str] = "New Chat"
    agent_type: Optional[str] = "customer"

class ConversationOut(BaseModel):
    id: str
    org_id: str
    user_id: str
    title: str
    agent_type: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    class Config:
        from_attributes = True

class ConversationUpdate(BaseModel):
    title: str

class MessageSend(BaseModel):
    content: str

class MessageOut(BaseModel):
    id: str
    conversation_id: str
    org_id: str
    user_id: str
    sender: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    citations: Optional[List[Dict[str, Any]]] = None
    card: Optional[Dict[str, Any]] = None
    created_at: datetime.datetime

# --- Admin Operations ---
class OrderStatusAdvance(BaseModel):
    new_status: str  # pending -> confirmed -> shipped -> delivered
    reason: Optional[str] = "Admin manual status advance"

class AdminActivitySummary(BaseModel):
    org_id: str
    time_window: str
    definition: str
    metrics: Dict[str, Any]

class AdminClientsToday(BaseModel):
    org_id: str
    date: str
    unique_customers_chatted: int
    new_signups_today: int
    definition: str

class AdminConversionRate(BaseModel):
    org_id: str
    time_window: str
    total_conversations: int
    successful_conversations: int
    conversion_rate_percentage: float
    definition: str

class AdminTopItems(BaseModel):
    org_id: str
    time_window: str
    top_items: List[Dict[str, Any]]
    secondary_items: List[Dict[str, Any]]
    definition: str
