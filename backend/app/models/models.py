import datetime
import json
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, DateTime, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from app.core.database import Base

class Organisation(Base):
    __tablename__ = "organisations"

    id = Column(String(50), primary_key=True)  # e.g. "org_a", "org_b"
    slug = Column(String(50), unique=True, index=True, nullable=False) # e.g. "himali-tea", "lotus-wellness"
    name = Column(String(100), nullable=False)
    tagline = Column(String(200), nullable=True)
    primary_color = Column(String(20), default="#1b4332")
    secondary_color = Column(String(20), default="#2d6a4f")
    accent_color = Column(String(20), default="#d4a373")
    agent_name = Column(String(50), default="Assistant")
    agent_role = Column(String(100), default="Agent")
    greeting = Column(Text, nullable=True)
    # retail = ordering agent, studio = booking agent. Only these two kinds exist.
    agent_kind = Column(String(20), nullable=False, default="retail")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    users = relationship("User", back_populates="organisation", cascade="all, delete-orphan")
    products = relationship("Product", back_populates="organisation", cascade="all, delete-orphan")
    services = relationship("Service", back_populates="organisation", cascade="all, delete-orphan")
    practitioners = relationship("Practitioner", back_populates="organisation", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(50), primary_key=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    email = Column(String(120), nullable=False, index=True)
    hashed_password = Column(String(200), nullable=False)
    name = Column(String(100), nullable=False)
    role = Column(String(20), default="customer")  # "customer" or "admin"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organisation = relationship("Organisation", back_populates="users")
    orders = relationship("Order", back_populates="user", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_org_user_email"),
    )


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(50), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    category = Column(String(80), nullable=False, index=True)
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organisation = relationship("Organisation", back_populates="products")

    __table_args__ = (
        UniqueConstraint("org_id", "sku", name="uq_org_product_sku"),
    )


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(50), primary_key=True)  # e.g. "ORD-1001"
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(50), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(30), default="pending", nullable=False)  # pending, confirmed, shipped, delivered, cancelled
    items_json = Column(Text, nullable=False, default="[]")  # JSON list of {sku, name, quantity, unit_price}
    total_price = Column(Float, nullable=False)
    shipping_address = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="orders")
    history = relationship("OrderStatusHistory", back_populates="order", cascade="all, delete-orphan")
    order_items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")

    @property
    def items(self):
        try:
            return json.loads(self.items_json) if self.items_json else []
        except Exception:
            return []

    @items.setter
    def items(self, val):
        self.items_json = json.dumps(val)


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(30), nullable=False)
    new_status = Column(String(30), nullable=False)
    changed_by = Column(String(100), nullable=False)
    reason = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    order = relationship("Order", back_populates="history")


class Service(Base):
    __tablename__ = "services"

    id = Column(String(50), primary_key=True)  # e.g. "srv_1"
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    price = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organisation = relationship("Organisation", back_populates="services")
    bookings = relationship("Booking", back_populates="service")


class Practitioner(Base):
    __tablename__ = "practitioners"

    id = Column(String(50), primary_key=True)  # e.g. "prac_1"
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    title = Column(String(120), nullable=False)
    specialties_json = Column(Text, nullable=False, default="[]")
    bio = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organisation = relationship("Organisation", back_populates="practitioners")
    bookings = relationship("Booking", back_populates="practitioner")

    @property
    def specialties(self):
        try:
            return json.loads(self.specialties_json) if self.specialties_json else []
        except Exception:
            return []

    @specialties.setter
    def specialties(self, val):
        self.specialties_json = json.dumps(val)


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(String(50), primary_key=True)  # e.g. "BKG-2001"
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(50), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id = Column(String(50), ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True)
    practitioner_id = Column(String(50), ForeignKey("practitioners.id", ondelete="CASCADE"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)  # Stored as naive UTC or studio time
    end_time = Column(DateTime, nullable=False, index=True)
    status = Column(String(30), default="confirmed", nullable=False)  # confirmed, rescheduled, cancelled
    cancellation_fee = Column(Float, default=0.0)
    reschedule_count = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="bookings")
    service = relationship("Service", back_populates="bookings")
    practitioner = relationship("Practitioner", back_populates="bookings")


class Holiday(Base):
    __tablename__ = "holidays"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    holiday_date = Column(String(20), nullable=False)  # "YYYY-MM-DD"
    name = Column(String(100), nullable=False)


class WeeklyOpeningHours(Base):
    __tablename__ = "weekly_opening_hours"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    day_of_week = Column(String(20), nullable=False)  # "Monday", "Tuesday", etc.
    open_time = Column(String(10), nullable=False)  # "08:00"
    close_time = Column(String(10), nullable=False)  # "19:00"
    is_closed = Column(Boolean, default=False)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String(50), primary_key=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(150), default="New Chat", nullable=False)
    agent_type = Column(String(20), default="customer")  # "customer" or "admin"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"

    id = Column(String(50), primary_key=True)
    conversation_id = Column(String(50), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    sender = Column(String(20), nullable=False)  # "user", "agent", "system"
    content = Column(Text, nullable=False)
    tool_calls_json = Column(Text, nullable=True)  # JSON list of tools called during turn
    citations_json = Column(Text, nullable=True)   # JSON list of {doc, section, excerpt}
    card_json = Column(Text, nullable=True)        # JSON for interactive rich cards
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    doc_name = Column(String(100), nullable=False, index=True)
    section_name = Column(String(150), nullable=False)
    content = Column(Text, nullable=False)
    embedding_json = Column(Text, nullable=True)  # Float array as JSON


class CustomerMemory(Base):
    __tablename__ = "customer_memories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_key = Column(String(50), nullable=False)  # e.g. "usual_tea", "preferred_practitioner"
    memory_value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "memory_key", name="uq_org_user_memory"),
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    order_id = Column(String(50), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(50), nullable=False)
    name = Column(String(150), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Float, nullable=False)
    subtotal = Column(Float, nullable=False)

    order = relationship("Order", back_populates="order_items")
    product = relationship("Product")


class ActionProposal(Base):
    __tablename__ = "action_proposals"

    id = Column(String(50), primary_key=True)  # e.g. "prop_abc123"
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(50), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    conversation_id = Column(String(50), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type = Column(String(50), nullable=False)  # "create_order", "update_order", "cancel_order", "create_booking", "reschedule_booking", "cancel_booking"
    payload_json = Column(Text, nullable=False)  # Full staged parameters as JSON
    summary_text = Column(Text, nullable=False)  # Human-readable summary
    status = Column(String(30), default="pending", nullable=False)  # "pending", "confirmed", "rejected", "expired"
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User")


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    org_id = Column(String(50), ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    sku = Column(String(50), nullable=False)
    delta = Column(Integer, nullable=False)  # e.g. -2 or +10
    reason = Column(String(50), nullable=False)  # "order_created", "order_cancelled", "order_updated", "stockout", "restock"
    stock_after = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    product = relationship("Product")


class RevokedToken(Base):
    """Access tokens that were signed out before they expired. Checked on every request."""
    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    user_id = Column(String(50), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, default=datetime.datetime.utcnow)
