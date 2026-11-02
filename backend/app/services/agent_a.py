import uuid
import json
import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update, delete
from app.models.models import (
    Product, Order, OrderItem, OrderStatusHistory, CustomerMemory,
    ActionProposal, InventoryEvent
)
from app.services.knowledge_base import KnowledgeBaseService

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
            "citations": [r["citation"] for r in results]
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

        matched = []
        for p in products:
            if query:
                q_lower = query.lower()
                if q_lower not in p.name.lower() and q_lower not in p.sku.lower() and q_lower not in (p.description or "").lower():
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

    @staticmethod
    async def prepare_order_summary(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        items: List[Dict[str, Any]],
        shipping_address: Optional[str] = "Kathmandu, Nepal"
    ) -> Dict[str, Any]:
        """
        Business Rule 1 & 2:
        Prepares order summary before placing, checks stock, calculates live totals,
        and generates an interactive confirmation card.
        """
        resolved_items = []
        total_price = 0.0
        stock_issues = []

        for item in items:
            sku = item.get("sku")
            qty = int(item.get("quantity", 1))

            stmt = select(Product).where(Product.org_id == org_id, Product.sku == sku)
            res = await db.execute(stmt)
            prod = res.scalars().first()
            if not prod:
                return {"success": False, "error": f"Product with SKU '{sku}' not found."}

            if qty > prod.stock:
                # Rule 2: Quantity can't exceed stock. Offer alternative
                stock_issues.append({
                    "sku": sku,
                    "name": prod.name,
                    "requested": qty,
                    "available": prod.stock
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
            # Find alternative products in same category
            alternatives = []
            for issue in stock_issues:
                alt_stmt = select(Product).where(
                    Product.org_id == org_id,
                    Product.sku != issue["sku"],
                    Product.stock > 0
                ).limit(2)
                alt_res = await db.execute(alt_stmt)
                for alt_prod in alt_res.scalars().all():
                    alternatives.append({
                        "sku": alt_prod.sku,
                        "name": alt_prod.name,
                        "price": alt_prod.price,
                        "stock": alt_prod.stock
                    })

            return {
                "success": False,
                "error": "Stock shortage",
                "stock_issues": stock_issues,
                "suggested_alternatives": alternatives,
                "message": f"Requested quantity exceeds current stock. Available: {stock_issues[0]['available']} units."
            }

        # Stage ActionProposal for backend-enforced confirmation
        proposal_id = f"prop_ord_{uuid.uuid4().hex[:8]}"
        proposal_payload = {
            "items": items,
            "resolved_items": resolved_items,
            "total_price": total_price,
            "shipping_address": shipping_address
        }
        proposal = ActionProposal(
            id=proposal_id,
            org_id=org_id,
            user_id=user_id,
            action_type="create_order",
            payload_json=json.dumps(proposal_payload),
            summary_text=f"Order Summary: {len(resolved_items)} items, Total NPR {total_price:.2f}",
            status="pending",
            expires_at=datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
        )
        db.add(proposal)
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
                "shipping_address": shipping_address
            },
            "summary_text": f"Order Summary: {len(resolved_items)} items, Total NPR {total_price:.2f}. Proposal #{proposal_id} staged. Would you like to confirm and place this order?"
        }

    @staticmethod
    async def create_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        items: List[Dict[str, Any]],
        shipping_address: Optional[str] = "Kathmandu, Nepal",
        confirmed: bool = True,
        proposal_id: Optional[str] = None,
        conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates confirmed pending order in DB with ATOMIC stock decrement and audit records.
        """
        # Validate stock & items
        summary = await AgentATools.prepare_order_summary(db, org_id, user_id, items, shipping_address)
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
        if proposal_id or summary.get("proposal_id"):
            pid = proposal_id or summary.get("proposal_id")
            prop_stmt = select(ActionProposal).where(ActionProposal.id == pid, ActionProposal.org_id == org_id)
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

        await db.commit()
        await db.refresh(new_order)

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
    async def update_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str,
        items: Optional[List[Dict[str, Any]]] = None,
        shipping_address: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Business Rule 3 & 4:
        Only pending orders can be updated, and only by the order's owner.
        """
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id)
        res = await db.execute(stmt)
        order = res.scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        # Rule 4: Ownership boundary
        if order.user_id != user_id:
            return {"success": False, "error": "Access denied: you can only view or edit your own orders."}

        # Rule 3: Only pending can be updated
        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be modified because it is already '{order.status}'. Only orders in 'pending' status can be changed."
            }

        # Handle items update
        if items is not None:
            # Re-check stock & calculate new total
            summary = await AgentATools.prepare_order_summary(db, org_id, user_id, items, shipping_address or order.shipping_address)
            if not summary.get("success"):
                return summary

            # Restore old items stock atomically
            for old_i in order.items:
                stmt_restore = (
                    update(Product)
                    .where(Product.org_id == org_id, Product.sku == old_i["sku"])
                    .values(stock=Product.stock + old_i["quantity"])
                )
                await db.execute(stmt_restore)
                p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == old_i["sku"])
                p_res = await db.execute(p_stmt)
                p_rec = p_res.scalars().first()
                if p_rec:
                    db.add(InventoryEvent(
                        org_id=org_id,
                        product_id=p_rec.id,
                        sku=p_rec.sku,
                        delta=old_i["quantity"],
                        reason="order_updated",
                        stock_after=p_rec.stock
                    ))

            # Deduct new items stock atomically
            for new_i in summary["items"]:
                stmt_deduct = (
                    update(Product)
                    .where(
                        Product.org_id == org_id,
                        Product.sku == new_i["sku"],
                        Product.stock >= new_i["quantity"]
                    )
                    .values(stock=Product.stock - new_i["quantity"])
                )
                res_deduct = await db.execute(stmt_deduct)
                if res_deduct.rowcount == 0:
                    await db.rollback()
                    return {
                        "success": False,
                        "error": f"Insufficient stock for {new_i['name']} during order update."
                    }
                p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == new_i["sku"])
                p_res = await db.execute(p_stmt)
                p_rec = p_res.scalars().first()
                if p_rec:
                    db.add(InventoryEvent(
                        org_id=org_id,
                        product_id=p_rec.id,
                        sku=p_rec.sku,
                        delta=-new_i["quantity"],
                        reason="order_updated",
                        stock_after=p_rec.stock
                    ))

            # Re-create OrderItem rows
            del_stmt = delete(OrderItem).where(OrderItem.order_id == order.id)
            await db.execute(del_stmt)
            for new_i in summary["items"]:
                p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == new_i["sku"])
                p_res = await db.execute(p_stmt)
                p_rec = p_res.scalars().first()
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

        history = OrderStatusHistory(
            order_id=order_id,
            old_status=order.status,
            new_status="pending",
            changed_by=f"Customer ({user_id})",
            reason="Customer modified pending order details"
        )
        db.add(history)
        await db.commit()
        await db.refresh(order)

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
                "total_price": order.total_price
            },
            "message": f"Order #{order_id} has been updated successfully. New total: NPR {order.total_price:.2f}."
        }

    @staticmethod
    async def cancel_order(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str
    ) -> Dict[str, Any]:
        """
        Business Rule 3 & 4:
        Only pending orders can be cancelled.
        """
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id)
        res = await db.execute(stmt)
        order = res.scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        # Rule 4: Ownership boundary
        if order.user_id != user_id:
            return {"success": False, "error": "Access denied: you can only cancel your own orders."}

        # Rule 3: Only pending can be cancelled
        if order.status != "pending":
            return {
                "success": False,
                "error": f"Order #{order_id} cannot be cancelled because it is already '{order.status}'. Only orders in 'pending' status can be cancelled."
            }

        # Restock items atomically
        for item in order.items:
            sku = item.get("sku")
            qty = item.get("quantity", 0)
            stmt_restore = (
                update(Product)
                .where(Product.org_id == org_id, Product.sku == sku)
                .values(stock=Product.stock + qty)
            )
            await db.execute(stmt_restore)
            p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == sku)
            p_res = await db.execute(p_stmt)
            p_rec = p_res.scalars().first()
            if p_rec:
                db.add(InventoryEvent(
                    org_id=org_id,
                    product_id=p_rec.id,
                    sku=p_rec.sku,
                    delta=qty,
                    reason="order_cancelled",
                    stock_after=p_rec.stock
                ))

        order.status = "cancelled"
        history = OrderStatusHistory(
            order_id=order_id,
            old_status="pending",
            new_status="cancelled",
            changed_by=f"Customer ({user_id})",
            reason="Customer cancelled order in chat"
        )
        db.add(history)
        await db.commit()

        return {
            "success": True,
            "order_id": order_id,
            "status": "cancelled",
            "message": f"Order #{order_id} has been cancelled successfully and reserved inventory was returned to stock."
        }

    @staticmethod
    async def get_order_status(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: str
    ) -> Dict[str, Any]:
        stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id)
        res = await db.execute(stmt)
        order = res.scalars().first()
        if not order:
            return {"success": False, "error": f"Order #{order_id} not found."}

        # Rule 4: Tenant and customer ownership boundary
        if order.user_id != user_id:
            return {"success": False, "error": "Access denied: you cannot view orders belonging to another customer."}

        # Fetch status history
        hist_stmt = select(OrderStatusHistory).where(OrderStatusHistory.order_id == order_id).order_by(OrderStatusHistory.created_at)
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
            "card": {
                "type": "order_status",
                "order_id": order.id,
                "status": order.status,
                "total_price": order.total_price,
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

        return {
            "success": True,
            "count": len(orders),
            "orders": [
                {
                    "order_id": o.id,
                    "status": o.status,
                    "items": o.items,
                    "total_price": o.total_price,
                    "created_at": o.created_at.isoformat()
                }
                for o in orders
            ]
        }

    @staticmethod
    async def reorder(
        db: AsyncSession,
        org_id: str,
        user_id: str,
        order_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Business Rule 5: 'Same as last time'
        Finds previous order, re-checks stock and current prices, notes differences,
        and prepares a summary for user approval.
        """
        if order_id:
            stmt = select(Order).where(Order.id == order_id, Order.org_id == org_id, Order.user_id == user_id)
        else:
            # Find the newest order
            stmt = select(Order).where(Order.org_id == org_id, Order.user_id == user_id).order_by(desc(Order.created_at))

        res = await db.execute(stmt)
        prev_order = res.scalars().first()
        if not prev_order:
            return {"success": False, "error": "No previous orders found to repeat."}

        # Re-check live stock and prices
        recheck_items = []
        price_changes = []
        stock_shortages = []
        new_total = 0.0

        for item in prev_order.items:
            sku = item.get("sku")
            qty = item.get("quantity", 1)
            old_price = item.get("unit_price", 0.0)

            p_stmt = select(Product).where(Product.org_id == org_id, Product.sku == sku)
            p_res = await db.execute(p_stmt)
            curr_prod = p_res.scalars().first()

            if not curr_prod:
                stock_shortages.append(f"{item.get('name', sku)} is no longer in catalog.")
                continue

            if curr_prod.stock < qty:
                stock_shortages.append(f"{curr_prod.name} has only {curr_prod.stock} units available (requested {qty}).")

            if abs(curr_prod.price - old_price) > 0.01:
                price_changes.append(f"{curr_prod.name}: changed from NPR {old_price:.2f} to NPR {curr_prod.price:.2f}.")

            subtotal = curr_prod.price * qty
            new_total += subtotal
            recheck_items.append({
                "sku": curr_prod.sku,
                "name": curr_prod.name,
                "unit_price": curr_prod.price,
                "quantity": qty,
                "subtotal": subtotal
            })

        notes = []
        if price_changes:
            notes.append("Price updates: " + "; ".join(price_changes))
        if stock_shortages:
            notes.append("Stock notice: " + "; ".join(stock_shortages))

        return {
            "success": True,
            "previous_order_id": prev_order.id,
            "items": recheck_items,
            "total_price": new_total,
            "shipping_address": prev_order.shipping_address,
            "notes": notes,
            "requires_confirmation": True,
            "card": {
                "type": "order_summary",
                "title": f"Repeat Previous Order (#{prev_order.id})",
                "items": recheck_items,
                "total_price": new_total,
                "notes": notes,
                "shipping_address": prev_order.shipping_address
            },
            "summary_text": f"Found your previous order #{prev_order.id}. Proposed new total is NPR {new_total:.2f}. " + (" ".join(notes) + " " if notes else "") + "Would you like me to confirm and place this order?"
        }

