from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Order, Product
from app.models.schemas import OrderOut, OrderCreate, OrderUpdate, ProductOut
from app.services.agent_a import AgentATools

router = APIRouter(prefix="/orders", tags=["Orders (Himali Tea House)"])

@router.get("/products", response_model=List[ProductOut])
async def list_products(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Product).where(Product.org_id == current_user.org_id)
    if category:
        stmt = stmt.where(Product.category == category)
    res = await db.execute(stmt)
    return [ProductOut.from_orm(p) for p in res.scalars().all()]

@router.get("", response_model=List[OrderOut])
async def list_orders(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Order).where(
        Order.org_id == current_user.org_id,
        Order.user_id == current_user.id
    ).order_by(desc(Order.created_at))
    res = await db.execute(stmt)
    return [
        OrderOut(
            id=o.id,
            org_id=o.org_id,
            user_id=o.user_id,
            status=o.status,
            items=o.items,
            total_price=o.total_price,
            shipping_address=o.shipping_address,
            created_at=o.created_at,
            updated_at=o.updated_at
        )
        for o in res.scalars().all()
    ]

@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    stmt = select(Order).where(
        Order.id == order_id,
        Order.org_id == current_user.org_id
    )
    res = await db.execute(stmt)
    order = res.scalars().first()
    if not order or order.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found or cross-customer access prohibited."
        )

    return OrderOut(
        id=order.id,
        org_id=order.org_id,
        user_id=order.user_id,
        status=order.status,
        items=order.items,
        total_price=order.total_price,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at
    )

@router.post("", response_model=OrderOut)
async def create_order_endpoint(
    payload: OrderCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    items_dict = [{"sku": i.sku, "quantity": i.quantity} for i in payload.items]
    res = await AgentATools.create_order(
        db, current_user.org_id, current_user.id, items_dict, payload.shipping_address
    )
    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("message") or res.get("error")
        )

    order_id = res["order_id"]
    order_stmt = select(Order).where(Order.id == order_id)
    o_res = await db.execute(order_stmt)
    order = o_res.scalars().first()

    return OrderOut(
        id=order.id,
        org_id=order.org_id,
        user_id=order.user_id,
        status=order.status,
        items=order.items,
        total_price=order.total_price,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at
    )

@router.patch("/{order_id}", response_model=OrderOut)
async def update_order_endpoint(
    order_id: str,
    payload: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    items_dict = [{"sku": i.sku, "quantity": i.quantity} for i in payload.items] if payload.items else None
    res = await AgentATools.update_order(
        db, current_user.org_id, current_user.id, order_id, items_dict, payload.shipping_address
    )
    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error") or res.get("message")
        )

    order_stmt = select(Order).where(Order.id == order_id)
    o_res = await db.execute(order_stmt)
    order = o_res.scalars().first()

    return OrderOut(
        id=order.id,
        org_id=order.org_id,
        user_id=order.user_id,
        status=order.status,
        items=order.items,
        total_price=order.total_price,
        shipping_address=order.shipping_address,
        created_at=order.created_at,
        updated_at=order.updated_at
    )

@router.post("/{order_id}/cancel")
async def cancel_order_endpoint(
    order_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await AgentATools.cancel_order(db, current_user.org_id, current_user.id, order_id)
    if not res.get("success"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=res.get("error")
        )
    return res
