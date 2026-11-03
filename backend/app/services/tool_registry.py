"""Server-side tool schemas and dispatch. The model cannot choose the tenant."""
import json
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import User
from app.services.admin_agent import AdminAnalyticsTools
from app.services.agent_a import AgentATools
from app.services.agent_b import AgentBTools
from app.services.scheduling import SchedulingEngine

MUTATION_TOOLS = {
    "create_order",
    "update_order",
    "cancel_order",
    "reorder",
    "create_booking",
    "reschedule_booking",
    "cancel_booking",
}

_OBJ = {"type": "object", "properties": {}}


def _tool(name: str, description: str, properties: Dict[str, Any], required: List[str] | None = None) -> Dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []},
    }


RETAIL_TOOLS = [
    _tool("search_knowledge", "Search this organisation's policies, FAQs and product guides. Returns citations.", {"query": {"type": "string", "description": "Question"}}, ["query"]),
    _tool("search_products", "Find products by name, category or price. Returns live price and stock only.", {
        "query": {"type": "string", "description": "Name or SKU fragment"},
        "category": {"type": "string", "description": "e.g. Green Tea, Black Tea, Teaware"},
        "min_price": {"type": "number", "description": "NPR"},
        "max_price": {"type": "number", "description": "NPR"},
    }),
    _tool("create_order", "Stage an order summary. Does not place the order. The customer confirms the card.", {
        "items": {
            "type": "array",
            "description": "Lines to order",
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["sku", "quantity"],
            },
        },
        "shipping_address": {"type": "string"},
    }, ["items"]),
    _tool("update_order", "Stage an edit to a pending order. Does not change the order.", {
        "order_id": {"type": "string"},
        "shipping_address": {"type": "string"},
        "items": {
            "type": "array",
            "description": "Replacement lines. Omit to keep the current lines.",
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "quantity": {"type": "integer"},
                },
                "required": ["sku", "quantity"],
            },
        },
    }, ["order_id"]),
    _tool("cancel_order", "Stage cancellation of a pending order. Does not cancel it.", {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("get_order_status", "Status, items, total and history for one of the customer's orders.", {"order_id": {"type": "string"}}, ["order_id"]),
    _tool("list_my_orders", "The customer's orders, newest first.", {}),
    _tool("reorder", "For 'same as last time': stage the customer's previous order at today's prices and stock. Does not place it. Omit order_id to use the latest order.", {"order_id": {"type": "string"}}),
]

STUDIO_TOOLS = [
    _tool("search_knowledge", "Search this studio's services, policies and FAQs. Returns citations.", {"query": {"type": "string"}}, ["query"]),
    _tool("list_services", "Services with duration and price, plus the practitioners (ids and which services each offers). Call this first to get valid service and practitioner ids.", {}),
    _tool("get_opening_hours", "Weekly hours and holidays in Asia/Kathmandu.", {}),
    _tool("find_available_slots", "Free slots for a service on a date. Optional practitioner and part of day. Times are Asia/Kathmandu.", {
        "service_id": {"type": "string", "description": "id from list_services, e.g. srv_1"},
        "date": {"type": "string", "description": "YYYY-MM-DD or a relative phrase such as 'next Tuesday'"},
        "practitioner_id": {"type": "string", "description": "id such as prac_2 from list_services; omit to include everyone who offers the service"},
        "part_of_day": {"type": "string", "description": "morning, afternoon or evening"},
    }, ["service_id", "date"]),
    _tool("create_booking", "Stage a booking summary. Does not book the slot.", {
        "service_id": {"type": "string"},
        "practitioner_id": {"type": "string"},
        "start_time": {"type": "string", "description": "ISO time in Asia/Kathmandu, copied from a find_available_slots result"},
    }, ["service_id", "practitioner_id", "start_time"]),
    _tool("reschedule_booking", "Stage a move to a new time. Does not move the booking.", {
        "booking_id": {"type": "string"},
        "new_start_time": {"type": "string"},
    }, ["booking_id", "new_start_time"]),
    _tool("cancel_booking", "Stage a cancellation, including the fee if one applies. Does not cancel.", {"booking_id": {"type": "string"}}, ["booking_id"]),
    _tool("list_my_bookings", "The customer's bookings.", {}),
]

ADMIN_TOOLS = [
    _tool("get_activity_summary", "Read-only activity summary for this organisation.", {"days": {"type": "integer"}}),
    _tool("get_clients_today", "Read-only count of customers who chatted and new sign-ups today.", {}),
    _tool("get_conversion_rate", "Read-only conversion rate and its definition.", {"days": {"type": "integer"}}),
    _tool("get_top_items", "Read-only top products or services.", {}),
]


def tools_for(agent_kind: str, is_admin: bool) -> List[Dict[str, Any]]:
    if is_admin:
        return ADMIN_TOOLS
    if agent_kind == "studio":
        return STUDIO_TOOLS
    return RETAIL_TOOLS


def validate_call(schema: Dict[str, Any], args: Dict[str, Any]) -> str | None:
    if not isinstance(args, dict):
        return "Tool arguments must be an object."
    required = schema.get("parameters", {}).get("required") or []
    for key in required:
        if args.get(key) in (None, "", []):
            return f"Missing required argument '{key}'."
    return None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _days(value: Any) -> int:
    try:
        return max(1, min(int(value), 365)) if value not in (None, "") else 30
    except (TypeError, ValueError):
        return 30


def _strip(args: Dict[str, Any]) -> Dict[str, Any]:
    blocked = {"org_id", "user_id", "confirmed", "proposal_id", "manage_transaction"}
    return {key: value for key, value in (args or {}).items() if key not in blocked}


async def dispatch_tool(
    db: AsyncSession,
    user: User,
    conversation_id: str,
    name: str,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    args = _strip(args)
    org_id = user.org_id
    user_id = user.id
    if name == "search_knowledge":
        return await AgentATools.search_knowledge(db, org_id, str(args.get("query") or ""))
    if name == "search_products":
        return await AgentATools.search_products(
            db, org_id, query=args.get("query"), category=args.get("category"),
            min_price=_number(args.get("min_price")), max_price=_number(args.get("max_price")),
        )
    if name == "create_order":
        items = args.get("items") or []
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except json.JSONDecodeError:
                return {"success": False, "error": "items must be a list of {sku, quantity}."}
        return await AgentATools.prepare_order_summary(
            db, org_id, user_id, items, args.get("shipping_address") or "Kathmandu, Nepal",
            conversation_id=conversation_id,
        )
    if name == "update_order":
        return await AgentATools.propose_update_order(
            db, org_id, user_id, str(args.get("order_id")),
            items=args.get("items"), shipping_address=args.get("shipping_address"),
            conversation_id=conversation_id,
        )
    if name == "cancel_order":
        return await AgentATools.propose_cancel_order(db, org_id, user_id, str(args.get("order_id")), conversation_id)
    if name == "get_order_status":
        return await AgentATools.get_order_status(db, org_id, user_id, str(args.get("order_id")))
    if name == "list_my_orders":
        return await AgentATools.list_my_orders(db, org_id, user_id)
    if name == "reorder":
        return await AgentATools.reorder(db, org_id, user_id, args.get("order_id"), conversation_id=conversation_id)
    if name == "list_services":
        return await AgentBTools.list_services(db, org_id)
    if name == "get_opening_hours":
        return await AgentBTools.get_opening_hours(db, org_id)
    if name == "find_available_slots":
        date_value = str(args.get("date") or "")
        if date_value and not date_value[:4].isdigit():
            try:
                date_value = SchedulingEngine.resolve_relative_datetime_kathmandu(date_value).strftime("%Y-%m-%d")
            except ValueError as exc:
                return {"success": False, "error": str(exc) + " Ask the customer for a date or use YYYY-MM-DD."}
        return await AgentBTools.find_available_slots(
            db, org_id, str(args.get("service_id")), date_value, args.get("practitioner_id"),
            user_id=user_id, part_of_day=args.get("part_of_day"),
        )
    if name == "create_booking":
        return await AgentBTools.prepare_booking_summary(
            db, org_id, user_id, str(args.get("service_id")), str(args.get("practitioner_id")),
            str(args.get("start_time")), conversation_id=conversation_id,
        )
    if name == "reschedule_booking":
        return await AgentBTools.propose_reschedule(
            db, org_id, user_id, str(args.get("booking_id")), str(args.get("new_start_time")), conversation_id
        )
    if name == "cancel_booking":
        return await AgentBTools.propose_cancel_booking(db, org_id, user_id, str(args.get("booking_id")), conversation_id)
    if name == "list_my_bookings":
        return await AgentBTools.list_my_bookings(db, org_id, user_id)
    if name == "get_activity_summary":
        return await AdminAnalyticsTools.get_activity_summary(db, org_id, _days(args.get("days")))
    if name == "get_clients_today":
        return await AdminAnalyticsTools.get_clients_today(db, org_id)
    if name == "get_conversion_rate":
        return await AdminAnalyticsTools.get_conversion_rate(db, org_id, _days(args.get("days")))
    if name == "get_top_items":
        return await AdminAnalyticsTools.get_top_items(db, org_id)
    return {"success": False, "error": f"Tool '{name}' is not allowed."}
