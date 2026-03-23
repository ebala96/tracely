"""
Load categories.yml into the PostgreSQL categories table.
Seeds parent categories first, then subcategories with parent_id set.

Run from the project root:
    cd ~/tracely && uv run --project backend python scripts/seed_categories.py
"""
import asyncio
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import select
from db.postgres import AsyncSessionLocal, create_tables
from db.models import Category

CATEGORIES_FILE = Path(__file__).parent.parent / "categories.yml"


async def seed():
    await create_tables()

    with open(CATEGORIES_FILE) as f:
        data = yaml.safe_load(f)

    async with AsyncSessionLocal() as session:
        for cat in data["categories"]:
            # Upsert parent category
            result = await session.execute(
                select(Category).where(Category.slug == cat["slug"])
            )
            parent = result.scalar_one_or_none()
            if not parent:
                parent = Category(
                    name=cat["name"],
                    slug=cat["slug"],
                    icon=cat.get("icon"),
                    colour=cat.get("colour"),
                    parent_id=None,
                )
                session.add(parent)
                await session.flush()  # get parent.id before inserting children
                print(f"  added  {cat['slug']}")
            else:
                parent.name   = cat["name"]
                parent.icon   = cat.get("icon")
                parent.colour = cat.get("colour")
                await session.flush()
                print(f"  updated {cat['slug']}")

            for sub in cat.get("subcategories") or []:
                result = await session.execute(
                    select(Category).where(Category.slug == sub["slug"])
                )
                existing_sub = result.scalar_one_or_none()
                if existing_sub:
                    existing_sub.name   = sub["name"]
                    existing_sub.icon   = sub.get("icon")
                    existing_sub.colour = cat.get("colour")
                    print(f"    updated {sub['slug']}")
                else:
                    session.add(Category(
                        name=sub["name"],
                        slug=sub["slug"],
                        icon=sub.get("icon"),
                        colour=cat.get("colour"),  # inherit parent colour
                        parent_id=parent.id,
                    ))
                    print(f"    added  {sub['slug']}")

        await session.commit()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed())
