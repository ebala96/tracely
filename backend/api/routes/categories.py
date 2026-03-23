"""
GET    /api/categories         — list all categories
POST   /api/categories         — create a new category
PATCH  /api/categories/{id}    — update a category
DELETE /api/categories/{id}    — delete a category (transactions become uncategorised)
"""
from typing import Optional
from fastapi import APIRouter, HTTPException
from sqlalchemy import select, update
from pydantic import BaseModel

from db.models import Category, Transaction
from db.postgres import AsyncSessionLocal
from schemas.models import CategoryOut

router = APIRouter(prefix="/api", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = "📦"
    colour: Optional[str] = "#9CA3AF"


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    colour: Optional[str] = None


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories():
    async with AsyncSessionLocal() as session:
        # Return parents first (parent_id IS NULL), then subcategories — makes frontend grouping easy
        result = await session.execute(
            select(Category).order_by(Category.parent_id.nullsfirst(), Category.name)
        )
        return result.scalars().all()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryCreate):
    async with AsyncSessionLocal() as session:
        # Check slug uniqueness
        existing = (await session.execute(
            select(Category).where(Category.slug == body.slug)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")

        cat = Category(name=body.name, slug=body.slug, icon=body.icon, colour=body.colour)
        session.add(cat)
        await session.commit()
        await session.refresh(cat)
        return cat


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, body: CategoryUpdate):
    async with AsyncSessionLocal() as session:
        cat = (await session.execute(
            select(Category).where(Category.id == category_id)
        )).scalar_one_or_none()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

        if body.name is not None:
            cat.name = body.name
        if body.icon is not None:
            cat.icon = body.icon
        if body.colour is not None:
            cat.colour = body.colour

        await session.commit()
        await session.refresh(cat)
        return cat


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int):
    async with AsyncSessionLocal() as session:
        cat = (await session.execute(
            select(Category).where(Category.id == category_id)
        )).scalar_one_or_none()
        if not cat:
            raise HTTPException(status_code=404, detail="Category not found")

        # Uncategorise all transactions in this category
        await session.execute(
            update(Transaction)
            .where(Transaction.category_id == category_id)
            .values(category_id=None)
        )
        await session.delete(cat)
        await session.commit()
