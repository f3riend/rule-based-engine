"""Resource sync from Fake API and local DB reads."""

import os
import time

import requests

from db import get_db, now_iso

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000/api/ai/v1")
TOKEN = os.environ.get("API_TOKEN", "aio_test_token")

HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def _api_get(path, params=None):
    r = requests.get(
        f"{API_URL}{path}",
        headers=HEADERS,
        params=params or {},
        timeout=30,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    body = r.json()
    return body.get("data")


def fetch_store(store_id: int):
    return _api_get(f"/resources/stores/{store_id}")


def fetch_item(item_id: int, include_store: bool = True):
    params = {"include": "store"} if include_store else None
    return _api_get(f"/resources/items/{item_id}", params=params)


def fetch_order(order_id: int):
    return _api_get(f"/resources/orders/{order_id}")


def fetch_events(cursor: int):
    """Listener polling — direct DB via timeline_service (no HTTP)."""
    from timeline_service import fetch_events_after_cursor

    return fetch_events_after_cursor(cursor=cursor, limit=100)


def upsert_store(store, status: str | None = None, user_id: int = 1):
    conn = get_db()
    store_status = status or store.get("status", "active")
    conn.execute(
        """
        INSERT OR REPLACE INTO stores (
            id, user_id, name, owner, instagram, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            store["id"],
            user_id,
            store["name"],
            store["owner"],
            store.get("instagram"),
            store_status,
            store["created_at"],
            store["updated_at"],
        ),
    )
    conn.commit()
    conn.close()
    print(f"[SYNC] Store synced #{store['id']} (status={store_status})")


def upsert_item(item, status: str | None = None, user_id: int = 1):
    conn = get_db()
    item_status = status or item.get("status", "active")
    conn.execute(
        """
        INSERT OR REPLACE INTO items (
            id, store_id, user_id, name, price, stock, sales,
            category, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["id"],
            item["store_id"],
            user_id,
            item["name"],
            item["price"],
            item["stock"],
            item["sales"],
            item.get("category"),
            item_status,
            item["created_at"],
            item["updated_at"],
        ),
    )
    conn.commit()
    conn.close()
    print(f"[SYNC] Item synced #{item['id']} (status={item_status})")


def upsert_order(order):
    conn = get_db()
    conn.execute(
        """
        INSERT OR REPLACE INTO orders (
            id, store_id, item_id, quantity, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order["id"],
            order["store_id"],
            order["item_id"],
            order["quantity"],
            order["status"],
            order["created_at"],
            order["updated_at"],
        ),
    )
    conn.commit()
    conn.close()
    print(f"[SYNC] Order synced #{order['id']}")


def mark_store_status(store_id: int, status: str):
    conn = get_db()
    conn.execute(
        "UPDATE stores SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), store_id),
    )
    conn.commit()
    conn.close()


def mark_item_status(item_id: int, status: str):
    conn = get_db()
    conn.execute(
        "UPDATE items SET status=?, updated_at=? WHERE id=?",
        (status, now_iso(), item_id),
    )
    conn.commit()
    conn.close()


def get_store(store_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM stores WHERE id=?", (store_id,)
    ).fetchone()
    conn.close()
    return row


def get_item(item_id: int):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM items WHERE id=?", (item_id,)
    ).fetchone()
    conn.close()
    return row


def build_rule_context(subject_type: str, subject_id: int, event: dict):
    """Build evaluation context with defaults for rule engine."""
    context = {}

    if subject_type == "Store":
        store = fetch_store(subject_id)
        if store:
            store = dict(store)
            store.setdefault("active", True)
            store.setdefault("status", "active")
            context["store"] = store

    elif subject_type == "Item":
        item = fetch_item(subject_id)
        if item:
            item = dict(item)
            item.setdefault("status", "active")
            context["item"] = item

            changes = event.get("changes") or {}
            stock_change = changes.get("stock")
            if stock_change and "to" in stock_change:
                context["item"]["stock"] = stock_change["to"]

            payload = event.get("payload") or {}
            if "new_stock" in payload:
                context["item"]["stock"] = payload["new_stock"]

    elif subject_type == "Order":
        order = fetch_order(subject_id)
        if order:
            context["order"] = dict(order)

    return context
