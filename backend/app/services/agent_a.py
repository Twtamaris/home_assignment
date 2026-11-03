import re
import uuid
import json
import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update, delete
from app.models.models import (
    Product, Order, OrderItem, OrderStatusHistory, CustomerMemory,
    ActionProposal, InventoryEvent
)
from app.services.knowledge_base import KnowledgeBaseService

PROPOSAL_TTL_MINUTES = 30

_SEARCH_STOPWORDS = {
    "the", "any", "some", "you", "your", "have", "has", "got", "want", "like", "need", "buy", "order",
    "please", "show", "find", "list", "what", "which", "are", "there", "for", "with", "and", "tea", "teas",
    "price", "prices", "stock", "much", "does", "cost", "how", "can", "get", "me", "my", "all", "under",
    "below", "than", "do", "in", "is", "it", "of", "to", "on", "at", "be", "we", "our", "available",
    "sell", "selling", "looking", "something", "anything", "about", "tell", "give", "more", "less",
}


class AgentATools:
    """
    Ordering Agent Tools for Himali Tea House (Org A).
    Enforces all 5 core business rules:
    1. Pre-order/change confirmation summary.
    2. Stock check & alternative offer on stock shortage.
    3. Pending-only modification/cancellation policy.
    4. Strict customer ownership boundary (only own orders).
    5. 'Same as last time' live price & stock re-check.
    """

    @staticmethod
    async def search_knowledge(db: AsyncSession, org_id: str, query: str) -> Dict[str, Any]:
        results = await KnowledgeBaseService.search_knowledge(db, org_id, query, top_k=3)
        return {
            "success": True,
            "query": query,
            "results": results,
            "answerable": bool(results),
            "note": (
                "Answer only from these passages and cite them. Prices and stock are not in the knowledge base: use search_products."
                if results else
                "No relevant passage found. Say you do not have that information; do not guess."
            ),
            "citations": [
                {
                    "doc": result.get("doc_name") or "Knowledge",
                    "section": result.get("section_name") or "",
                    "excerpt": result.get("content") or "",
                }
                for result in results
            ]
        }

    @staticmethod
    async def search_products(
        db: AsyncSession,
        org_id: str,
        query: Optional[str] = None,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None
    ) -> Dict[str, Any]:
        stmt = select(Product).where(Product.org_id == org_id)
        if category:
            stmt = stmt.where(Product.category.ilike(f"%{category}%"))

        result = await db.execute(stmt)
        products = result.scalars().all()

        terms = [t for t in re.findall(r"[a-z0-9\-]+", (query or "").lower()) if len(t) > 2 and t not in _SEARCH_STOPWORDS]
        matched = []
        for p in products:
            if terms:
                haystack = f"{p.sku} {p.name} {p.category} {p.description or ''}".lower()
                # Every meaningful word must appear somewhere in the product record.
                if not all(term in haystack or term.rstrip("s") in haystack for term in terms):
                    continue
            if min_price is not None and p.price < min_price:
                continue
            if max_price is not None and p.price > max_price:
                continue

            matched.append({
                "sku": p.sku,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "stock": p.stock,
                "description": p.description,
                "in_stock": p.stock > 0
            })

        return {
            "success": True,
            "count": len(matched),
            "products": matched
        }

    MAX_LINE_QUANTITY = 50

    @staticmethod
    def normalise_items(items: Any) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """
        Validates order lines from the model or a client. Returns (lines, error).
        Quantities must be whole numbers from 1 up. Repeated SKUs are merged so that
        stock is checked against the combined quantity.
        """
        if not isinstance(items, list) or not items:
            return [], "No order items specified."
        merged: Dict[str, int] = {}
        for raw in items:
            if not isinstance(raw, dict):
                return [], "Each order line must be an object with a sku and a quantity."
            sku = str(raw.get("sku") or "").strip().upper()
            if not sku:
                return [], "Each order line needs a sku."
            quantity = raw.get("quantity", 1)
            try:
                numeric = float(quantity)
            except (TypeError, ValueError):
                return [], f"Quantity for {sku} must be a whole number."
            if numeric != int(numeric) or int(numeric) < 1:
                return [], f"Quantity for {sku} must be a whole number of at least 1."
            if int(numeric) > AgentATools.MAX_LINE_QUANTITY:
                return [], f"Quantity for {sku} cannot exceed {AgentATools.MAX_LINE_QUANTITY} per order."
            merged[sku] = merged.get(sku, 0) + int(numeric)
        return [{"sku": sku, "quantity": qty} for sku, qty in merged.items()], None

    @staticmethod
    async def _alternatives_for(db: AsyncSession, org_id: str, short: List[Dict[str, Any]], exclude: set) -> List[Dict[str, Any]]:
        """In-stock products to offer instead of short ones: same category first."""
        alternatives: List[Dict[str, Any]] = []
        seen = set(exclude)
        for issue in short:
            same_category = (await db.execute(
                select(Product).where(
                    Product.org_id == org_id,
                    Product.category == issue["category"],
                    Product.stock > 0,
                ).order_by(Product.stock.desc())
            )).scalars().all()
            others = (await db.execute(
                select(Product).where(Product.org_id == org_id, Product.category != issue["category"], Product.stock > 0)
                .order_by(Product.stock.desc())
            )).scalars().all()
            picked = 0
            for product in list(same_category) + list(others):
                if product.sku in seen:
                    continue
                seen.add(product.sku)
                alternatives.append({
                    "sku": product.sku,
                    "name": product.name,
                    "category": product.category,
                    "price": product.price,
                    "stock": product.stock,
                    "same_category": product.category == issue["category"],
                })
                picked += 1
                if picked >= 2:
                    break
        return alternatives

    @staticmethod
    async def prepare_order_summary(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        items: List[Dict[str, Any]],
        shipping_address: Optional[str] = "Kathmandu, Nepal",
        stage_proposal: bool = True,
        conversation_id: Optional[str] = None,
        commit: bool = True,
        reserved: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Business Rule 1 & 2:
        Prepares order summary before placing, checks stock, calculates live totals,
        and generates an interactive confirmation card.

        `reserved` is the quantity per SKU that an existing pending order already holds.
        When editing that order those units count as available again.
        """
        lines, problem = AgentATools.normalise_items(items)
        if problem:
            return {"success": False, "error": problem}
        reserved = {key.upper(): value for key, value in (reserved or {}).items()}

        resolved_items = []
        total_price = 0.0
        stock_issues = []

        for line in lines:
            sku, qty = line["sku"], line["quantity"]
            prod = (await db.execute(
                select(Product).where(Product.org_id == org_id, Product.sku == sku)
            )).scalars().first()
            if not prod:
                return {"success": False, "error": f"Product with SKU '{sku}' not found."}

            available = prod.stock + reserved.get(prod.sku.upper(), 0)
            if qty > available:
                stock_issues.append({
                    "sku": prod.sku,
                    "name": prod.name,
                    "category": prod.category,
                    "requested": qty,
                    "available": available,
                })

            item_subtotal = prod.price * qty
            total_price += item_subtotal
            resolved_items.append({
                "sku": prod.sku,
                "name": prod.name,
                "unit_price": prod.price,
                "quantity": qty,
                "subtotal": item_subtotal
            })

        if stock_issues:
            alternatives = await AgentATools._alternatives_for(
                db, org_id, stock_issues, exclude={item["sku"] for item in resolved_items}
            )
            detail = "; ".join(
                f"{issue['name']}: only {issue['available']} in stock, {issue['requested']} requested"
                for issue in stock_issues
            )
            return {
                "success": False,
                "error": "Stock shortage",
                "stock_issues": stock_issues,
                "suggested_alternatives": alternatives,
                "message": f"Requested quantity exceeds current stock ({detail}). Offer the customer a smaller quantity or one of the suggested alternatives."
            }

        proposal_id = None
        if stage_proposal:
            # Stage ActionProposal for backend-enforced confirmation
            proposal_id = f"prop_ord_{uuid.uuid4().hex[:8]}"
            proposal_payload = {
                "items": lines,
                "resolved_items": resolved_items,
                "total_price": total_price,
                "shipping_address": shipping_address
            }
            proposal = ActionProposal(
                id=proposal_id,
                org_id=org_id,
                user_id=user_id,
                conversation_id=conversation_id,
                action_type="create_order",
                payload_json=json.dumps(proposal_payload),
                summary_text=f"Order Summary: {len(resolved_items)} items, Total NPR {total_price:.2f}",
                status="pending",
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=PROPOSAL_TTL_MINUTES)
            )
            db.add(proposal)
            if commit:
                await db.commit()

        return {
            "success": True,
            "is_summary": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "items": resolved_items,
            "total_price": total_price,
            "shipping_address": shipping_address,
            "card": {
                "type": "order_summary",
                "proposal_id": proposal_id,
                "title": "Please Confirm Your Order",
                "items": resolved_items,
                "total_price": total_price,
                "shipping_address": shipping_address,
                "action": "create",
                "confirm_label": "Confirm Order",
            },
            "summary_text": f"Order Summary: {len(resolved_items)} items, Total NPR {total_price:.2f}. " + (f"Proposal #{proposal_id} staged. " if proposal_id else "") + "Would you like to confirm and place this order?"
        }

    @staticmethod
    async def create_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        items: Optional[List[Dict[str, Any]]] = None,
        shipping_address: Optional[str] = "Kathmandu, Nepal",
        confirmed: bool = True,
        proposal_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Creates confirmed pending order in DB with ATOMIC stock decrement and audit records.
        Strictly adheres to exact items and pricing from ActionProposal when proposal_id is provided.
        """
        existing_prop = None
        if proposal_id:
            prop_stmt = select(ActionProposal).where(ActionProposal.id == proposal_id, ActionProposal.org_id == org_id)
            prop_res = await db.execute(prop_stmt)
            existing_prop = prop_res.scalars().first()
            if existing_prop:
                prop_data = json.loads(existing_prop.payload_json)
                if not items:
                    items = prop_data.get("items", [])
                if not shipping_address or shipping_address == "Kathmandu, Nepal":
                    shipping_address = prop_data.get("shipping_address", shipping_address)

        if not items:
            return {"success": False, "error": "No order items specified to create order."}

        # Validate stock & items without creating a duplicate proposal
        summary = await AgentATools.prepare_order_summary(
            db, org_id, user_id, items, shipping_address, stage_proposal=False
        )
        if not summary.get("success"):
            return summary

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        resolved_items = summary["items"]
        total_price = summary["total_price"]

        # Atomic stock decrement and InventoryEvent logging
        for item in resolved_items:
            sku = item["sku"]
            qty = item["quantity"]

            # ATOMIC SQL UPDATE: ensures stock >= qty at DB level
            stmt = (
                update(Product)
                .where(
                    Product.org_id == org_id,
                    Product.sku == sku,
                    Product.stock >= qty
                )
                .values(stock=Product.stock - qty)
            )
            res = await db.execute(stmt)
            if res.rowcount == 0:
                if manage_transaction:
                    await db.rollback()
                return {
                    "success": False,
                    "error": "Concurrent stock reservation failure",
                    "message": f"Sorry, {item['name']} just ran out of stock or lacks requested quantity."
                }

            # Fetch updated product record for accurate post-decrement balance
            p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == sku)
            p_res = await db.execute(p_stmt)
            p_record = p_res.scalars().first()

            # Record InventoryEvent for out-of-stock and inventory analytics
            inv_event = InventoryEvent(
                org_id=org_id,
                product_id=p_record.id,
                sku=p_record.sku,
                delta=-qty,
                reason="order_created",
                stock_after=p_record.stock
            )
            db.add(inv_event)

        new_order = Order(
            id=order_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            status="pending",
            items_json="",
            total_price=total_price,
            shipping_address=shipping_address
        )
        new_order.items = resolved_items
        db.add(new_order)

        # Create relational OrderItem rows
        for item in resolved_items:
            p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == item["sku"])
            p_res = await db.execute(p_stmt)
            p_record = p_res.scalars().first()
            if p_record:
                order_item = OrderItem(
                    org_id=org_id,
                    order_id=order_id,
                    product_id=p_record.id,
                    sku=item["sku"],
                    name=item["name"],
                    quantity=item["quantity"],
                    unit_price=item["unit_price"],
                    subtotal=item["subtotal"]
                )
                db.add(order_item)

        # Log initial status in history
        history = OrderStatusHistory(
            order_id=order_id,
            old_status="none",
            new_status="pending",
            changed_by=f"Customer ({user_id})",
            reason="Initial order placement"
        )
        db.add(history)

        # Update action proposal status if proposal_id was passed
        if existing_prop:
            existing_prop.status = "confirmed"
        elif proposal_id:
            prop_stmt = select(ActionProposal).where(ActionProposal.id == proposal_id, ActionProposal.org_id == org_id)
            prop_res = await db.execute(prop_stmt)
            prop = prop_res.scalars().first()
            if prop:
                prop.status = "confirmed"

        # Save to customer memory (e.g. usual tea)
        if resolved_items:
            mem_stmt = select(CustomerMemory).where(
                CustomerMemory.org_id == org_id,
                CustomerMemory.user_id == user_id,
                CustomerMemory.memory_key == "usual_tea"
            )
            mem_res = await db.execute(mem_stmt)
            mem = mem_res.scalars().first()
            if not mem:
                mem = CustomerMemory(
                    org_id=org_id,
                    user_id=user_id,
                    memory_key="usual_tea",
                    memory_value=resolved_items[0]["name"]
                )
                db.add(mem)
            else:
                mem.memory_value = resolved_items[0]["name"]

        if manage_transaction:
            await db.commit()
            await db.refresh(new_order)
        else:
            await db.flush()

        return {
            "success": True,
            "order_id": order_id,
            "status": "pending",
            "items": resolved_items,
            "total_price": total_price,
            "shipping_address": shipping_address,
            "card": {
                "type": "order_placed",
                "order_id": order_id,
                "status": "pending",
                "items": resolved_items,
                "total_price": total_price
            },
            "message": f"Your order #{order_id} has been placed successfully in 'pending' status. Total: NPR {total_price:.2f}."
        }

    @staticmethod
    async def restock(db: AsyncSession, org_id: str, order_items: List[Dict[str, Any]], reason: str) -> None:
        """Return reserved units to stock and log an InventoryEvent per line."""
        for item in order_items:
            sku = item.get("sku")
            qty = int(item.get("quantity", 0))
            if qty <= 0:
                continue
            await db.execute(
                update(Product)
                .where(Product.org_id == org_id, Product.sku == sku)
                .values(stock=Product.stock + qty)
            )
            product = (await db.execute(
                select(Product).where(Product.org_id == org_id, Product.sku == sku)
            )).scalars().first()
            if product:
                await db.refresh(product)
                db.add(InventoryEvent(
                    org_id=org_id,
                    product_id=product.id,
                    sku=product.sku,
                    delta=qty,
                    reason=reason,
                    stock_after=product.stock,
                ))

    @staticmethod
    async def update_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str,
        items: Optional[List[Dict[str, Any]]] = None,
        shipping_address: Optional[str] = None,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Business Rule 3 & 4:
        Only pending orders can be updated, and only by the order's owner.
        The query is scoped to the owner, so another customer's order id looks like a missing one.
        """
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        order = (await db.execute(stmt)).scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        # Rule 3: Only pending can be updated
        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be modified because it is already '{order.status}'. Only orders in 'pending' status can be changed."
            }
        if items is None and not shipping_address:
            return {"success": False, "error": "Nothing to change: give new items or a new shipping address."}

        if items is not None:
            # The units this order already holds count as available for its own edit.
            reserved = {line["sku"]: int(line["quantity"]) for line in order.items}
            summary = await AgentATools.prepare_order_summary(
                db, org_id, user_id, items, shipping_address or order.shipping_address,
                stage_proposal=False, reserved=reserved,
            )
            if not summary.get("success"):
                return summary

            await AgentATools.restock(db, org_id, order.items, "order_updated")

            for new_i in summary["items"]:
                res_deduct = await db.execute(
                    update(Product)
                    .where(
                        Product.org_id == org_id,
                        Product.sku == new_i["sku"],
                        Product.stock >= new_i["quantity"]
                    )
                    .values(stock=Product.stock - new_i["quantity"])
                )
                if res_deduct.rowcount == 0:
                    if manage_transaction:
                        await db.rollback()
                    return {
                        "success": False,
                        "error": f"Insufficient stock for {new_i['name']} during order update."
                    }
                p_rec = (await db.execute(
                    select(Product).where(Product.org_id == org_id, Product.sku == new_i["sku"])
                )).scalars().first()
                if p_rec:
                    await db.refresh(p_rec)
                    db.add(InventoryEvent(
                        org_id=org_id,
                        product_id=p_rec.id,
                        sku=p_rec.sku,
                        delta=-new_i["quantity"],
                        reason="order_updated",
                        stock_after=p_rec.stock
                    ))

            # Re-create OrderItem rows
            await db.execute(delete(OrderItem).where(OrderItem.order_id == order.id))
            for new_i in summary["items"]:
                p_rec = (await db.execute(
                    select(Product).where(Product.org_id == org_id, Product.sku == new_i["sku"])
                )).scalars().first()
                if p_rec:
                    db.add(OrderItem(
                        org_id=org_id,
                        order_id=order.id,
                        product_id=p_rec.id,
                        sku=new_i["sku"],
                        name=new_i["name"],
                        quantity=new_i["quantity"],
                        unit_price=new_i["unit_price"],
                        subtotal=new_i["subtotal"]
                    ))

            order.items = summary["items"]
            order.total_price = summary["total_price"]

        if shipping_address:
            order.shipping_address = shipping_address

        db.add(OrderStatusHistory(
            order_id=order_id,
            old_status=order.status,
            new_status="pending",
            changed_by=f"Customer ({user_id})",
            reason="Customer modified pending order details"
        ))
        if manage_transaction:
            await db.commit()
            await db.refresh(order)
        else:
            await db.flush()

        return {
            "success": True,
            "order_id": order.id,
            "status": order.status,
            "items": order.items,
            "total_price": order.total_price,
            "shipping_address": order.shipping_address,
            "card": {
                "type": "order_updated",
                "order_id": order.id,
                "status": order.status,
                "items": order.items,
                "total_price": order.total_price,
                "shipping_address": order.shipping_address,
            },
            "message": f"Order #{order_id} has been updated successfully. New total: NPR {order.total_price:.2f}."
        }

    @staticmethod
    async def cancel_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str,
        manage_transaction: bool = True,
    ) -> Dict[str, Any]:
        """
        Business Rule 3 & 4:
        Only pending orders can be cancelled, and only by their owner.
        """
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        order = (await db.execute(stmt)).scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be cancelled because it is already '{order.status}'. Only orders in 'pending' status can be cancelled."
            }

        await AgentATools.restock(db, org_id, order.items, "order_cancelled")

        order.status = "cancelled"
        db.add(OrderStatusHistory(
            order_id=order_id,
            old_status="pending",
            new_status="cancelled",
            changed_by=f"Customer ({user_id})",
            reason="Customer cancelled order in chat"
        ))
        if manage_transaction:
            await db.commit()
        else:
            await db.flush()

        return {
            "success": True,
            "order_id": order_id,
            "status": "cancelled",
            "card": {
                "type": "order_cancelled",
                "order_id": order_id,
                "status": "cancelled",
                "items": order.items,
                "total_price": order.total_price,
            },
            "message": f"Order #{order_id} has been cancelled successfully and reserved inventory was returned to stock."
        }

    @staticmethod
    async def get_order_status(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str
    ) -> Dict[str, Any]:
        # Rule 4: scoped to tenant AND owner. Someone else's order reads as "not found".
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        order = (await db.execute(stmt)).scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        hist_stmt = select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id).order_by(OrderStatusHistory.created_at, OrderStatusHistory.id)
        hist_res = await db.execute(hist_stmt)
        histories = [
            {
                "new_status": h.new_status,
                "changed_by": h.changed_by,
                "reason": h.reason,
                "timestamp": h.created_at.isoformat()
            }
            for h in hist_res.scalars().all()
        ]

        return {
            "success": True,
            "order_id": order.id,
            "status": order.status,
            "items": order.items,
            "total_price": order.total_price,
            "shipping_address": order.shipping_address,
            "created_at": order.created_at.isoformat(),
            "status_history": histories,
            "editable": order.status == "pending",
            "card": {
                "type": "order_status",
                "order_id": order.id,
                "status": order.status,
                "items": order.items,
                "total_price": order.total_price,
                "shipping_address": order.shipping_address,
                "history": histories
            }
        }

    @staticmethod
    async def list_my_orders(
        db: AsyncSession,
        org_id: str,
        user_id: str
    ) -> Dict[str, Any]:
        stmt = select(Order).where(
            Order.org_id == org_id,
            Order.user_id == user_id
        ).order_by(desc(Order.created_at))
        res = await db.execute(stmt)
        orders = res.scalars().all()
        rows = [
            {
                "order_id": o.id,
                "status": o.status,
                "items": o.items,
                "total_price": o.total_price,
                "created_at": o.created_at.isoformat()
            }
            for o in orders
        ]
        return {
            "success": True,
            "count": len(rows),
            "orders": rows,
            "card": {"type": "order_list", "title": "Your orders", "orders": rows[:8]} if rows else None,
        }

    @staticmethod
    async def reorder(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Business Rule 5: 'Same as last time'
        Finds previous order, re-checks stock and current prices, notes differences,
        and stages a summary for approval. Without an order id, the newest order that
        was not cancelled is used.
        """
        stmt = select(Order).where(Order.org_id == org_id, Order.user_id == user_id)
        if order_id:
            stmt = stmt.where(Order.id == order_id)
        else:
            stmt = stmt.where(Order.status != "cancelled")
        prev_order = (await db.execute(stmt.order_by(desc(Order.created_at)))).scalars().first()
        if not prev_order:
            return {"success": False, "error": "No previous orders found to repeat."}

        recheck_lines = []
        price_changes = []
        stock_issues = []
        unavailable = []

        for item in prev_order.items:
            sku = item.get("sku")
            qty = int(item.get("quantity", 1))
            old_price = float(item.get("unit_price", 0.0))

            curr_prod = (await db.execute(
                select(Product).where(Product.org_id == org_id, Product.sku == sku)
            )).scalars().first()
            if not curr_prod:
                unavailable.append(f"{item.get('name', sku)} is no longer in the catalog.")
                continue
            if curr_prod.stock < qty:
                stock_issues.append({
                    "sku": curr_prod.sku, "name": curr_prod.name, "category": curr_prod.category,
                    "requested": qty, "available": curr_prod.stock,
                })
            if abs(curr_prod.price - old_price) > 0.01:
                price_changes.append(f"{curr_prod.name}: NPR {old_price:.2f} then, NPR {curr_prod.price:.2f} now.")
            recheck_lines.append({"sku": curr_prod.sku, "quantity": qty})

        notes = []
        if price_changes:
            notes.append("Price changes since order " + prev_order.id + ": " + " ".join(price_changes))
        for issue in stock_issues:
            notes.append(f"{issue['name']}: only {issue['available']} in stock (previously ordered {issue['requested']}).")
        notes.extend(unavailable)

        if stock_issues or unavailable or not recheck_lines:
            alternatives = await AgentATools._alternatives_for(
                db, org_id, stock_issues, exclude={line["sku"] for line in recheck_lines}
            ) if stock_issues else []
            return {
                "success": False,
                "requires_confirmation": False,
                "previous_order_id": prev_order.id,
                "notes": notes,
                "stock_issues": stock_issues,
                "suggested_alternatives": alternatives,
                "error": "Cannot stage a reorder until the stock issues are resolved.",
                "message": " ".join(notes) if notes else "No previous items can be reordered.",
            }

        summary = await AgentATools.prepare_order_summary(
            db, org_id, user_id, recheck_lines, prev_order.shipping_address,
            conversation_id=conversation_id,
        )
        if not summary.get("success"):
            return summary
        summary["previous_order_id"] = prev_order.id
        summary["previous_total"] = prev_order.total_price
        summary["notes"] = notes
        if summary.get("card"):
            summary["card"]["title"] = f"Repeat of order #{prev_order.id}"
            summary["card"]["previous_total"] = prev_order.total_price
            if notes:
                summary["card"]["notes"] = notes
        if notes:
            summary["summary_text"] = (" ".join(notes) + " ") + summary.get("summary_text", "")
        return summary

    @staticmethod
    async def propose_update_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str,
        items: Optional[List[Dict[str, Any]]] = None,
        shipping_address: Optional[str] = None,
        conversation_id: Optional[str] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Stage an edit. The order row is not changed until confirm."""
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        order = (await db.execute(stmt)).scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}
        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be modified because it is already '{order.status}'. Only orders in 'pending' status can be changed.",
            }
        if items is None and not shipping_address:
            return {"success": False, "error": "Nothing to change: give new items or a new shipping address."}
        next_items = items if items is not None else [
            {"sku": item.get("sku"), "quantity": item.get("quantity", 1)} for item in order.items
        ]
        reserved = {line["sku"]: int(line["quantity"]) for line in order.items}
        summary = await AgentATools.prepare_order_summary(
            db, org_id, user_id, next_items, shipping_address or order.shipping_address,
            stage_proposal=False, commit=False, reserved=reserved,
        )
        if not summary.get("success"):
            return summary
        proposal_id = f"prop_upd_{uuid.uuid4().hex[:8]}"
        payload = {
            "order_id": order.id,
            "items": next_items,
            "resolved_items": summary["items"],
            "total_price": summary["total_price"],
            "shipping_address": summary["shipping_address"],
            "previous_total": order.total_price,
        }
        proposal = ActionProposal(
            id=proposal_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            action_type="update_order",
            payload_json=json.dumps(payload),
            summary_text=f"Update order #{order.id} to NPR {summary['total_price']:.2f}",
            status="pending",
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=PROPOSAL_TTL_MINUTES),
        )
        db.add(proposal)
        if commit:
            await db.commit()
        card = summary["card"]
        card["proposal_id"] = proposal_id
        card["title"] = f"Confirm changes to order #{order.id}"
        card["action"] = "update"
        card["confirm_label"] = "Confirm Changes"
        card["previous_total"] = order.total_price
        if abs(order.total_price - summary["total_price"]) > 0.01:
            card["notes"] = [f"Total changes from NPR {order.total_price:.2f} to NPR {summary['total_price']:.2f} at current prices."]
        return {
            "success": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "card": card,
            "summary_text": proposal.summary_text + ". Nothing is changed until you confirm.",
            "total_price": summary["total_price"],
            "items": summary["items"],
        }

    @staticmethod
    async def propose_cancel_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        order = (await db.execute(stmt)).scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}
        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be cancelled because it is already '{order.status}'. Only orders in 'pending' status can be cancelled.",
            }
        proposal_id = f"prop_can_{uuid.uuid4().hex[:8]}"
        payload = {
            "order_id": order.id,
            "items": order.items,
            "total_price": order.total_price,
            "status": order.status,
        }
        summary = (
            f"Cancel pending order #{order.id} (NPR {order.total_price:.2f}). "
            "Reserved stock will be returned. No cancellation fee applies."
        )
        proposal = ActionProposal(
            id=proposal_id,
            org_id=org_id,
            user_id=user_id,
            conversation_id=conversation_id,
            action_type="cancel_order",
            payload_json=json.dumps(payload),
            summary_text=summary,
            status="pending",
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=PROPOSAL_TTL_MINUTES),
        )
        db.add(proposal)
        await db.commit()
        return {
            "success": True,
            "requires_confirmation": True,
            "proposal_id": proposal_id,
            "summary_text": summary,
            "card": {
                "type": "order_summary",
                "proposal_id": proposal_id,
                "title": f"Confirm cancellation of #{order.id}",
                "items": order.items,
                "total_price": order.total_price,
                "notes": ["Stock reserved for this pending order will be restored once."],
                "action": "cancel",
                "confirm_label": "Confirm Cancellation",
            },
        }
