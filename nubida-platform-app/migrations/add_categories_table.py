"""
Migration: Create categories table with initial 5 categories
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)

with engine.connect() as conn:
    # Create categories table
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            sort_order INTEGER DEFAULT 0,
            color VARCHAR(7),
            bg_color VARCHAR(7),
            is_active BOOLEAN DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    
    # Insert initial 5 categories (skip if already exist)
    initial_categories = [
        ('maker_coding', '메이커 코딩', 1, '#2563EB', '#EFF6FF'),
        ('ai_robot', 'AI·로봇', 2, '#7C3AED', '#F5F3FF'),
        ('software', '소프트웨어', 3, '#059669', '#ECFDF5'),
        ('design_creative', '디자인·창작', 4, '#D97706', '#FFFBEB'),
        ('math_science', '수학·과학', 5, '#DC2626', '#FEF2F2'),
    ]
    
    for key, name, sort_order, color, bg_color in initial_categories:
        result = conn.execute(text("SELECT id FROM categories WHERE key = :key"), {"key": key})
        if not result.fetchone():
            conn.execute(
                text("INSERT INTO categories (key, name, sort_order, color, bg_color) VALUES (:key, :name, :sort_order, :color, :bg_color)"),
                {"key": key, "name": name, "sort_order": sort_order, "color": color, "bg_color": bg_color}
            )
            print(f"  ✓ Inserted category: {name}")
        else:
            print(f"  - Already exists: {name}")
    
    conn.commit()
    print("✓ Categories migration complete!")
