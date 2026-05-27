import requests
import json
import time
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"
TOKEN = "aio_test_token"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}"
}

OUTPUT_FILE = "api_test_results.txt"


# =========================================================
# HELPERS
# =========================================================

results = []


def log(title, success, response=None, error=None):
    status = "PASS" if success else "FAIL"

    entry = {
        "title": title,
        "status": status,
        "timestamp": datetime.utcnow().isoformat(),
        "response": response,
        "error": error,
    }

    results.append(entry)

    print(f"[{status}] {title}")


def write_results():

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

        f.write("=" * 80 + "\n")
        f.write("FAKE AI API TEST RESULTS\n")
        f.write("=" * 80 + "\n\n")

        for r in results:

            f.write(f"TEST: {r['title']}\n")
            f.write(f"STATUS: {r['status']}\n")
            f.write(f"TIME: {r['timestamp']}\n")

            if r["error"]:
                f.write(f"ERROR:\n{r['error']}\n")

            if r["response"]:
                f.write("RESPONSE:\n")
                f.write(
                    json.dumps(
                        r["response"],
                        indent=2,
                        ensure_ascii=False
                    )
                )
                f.write("\n")

            f.write("\n" + "-" * 80 + "\n\n")

    print(f"\nResults written to: {OUTPUT_FILE}")


def test_get(title, endpoint, headers=None):

    try:

        r = requests.get(
            BASE_URL + endpoint,
            headers=headers or HEADERS,
            timeout=10,
        )

        try:
            data = r.json()
        except:
            data = r.text

        log(
            title=title,
            success=(200 <= r.status_code < 300),
            response={
                "status_code": r.status_code,
                "data": data,
            }
        )

    except Exception as e:

        log(
            title=title,
            success=False,
            error=str(e)
        )


def test_post(title, endpoint, payload=None, headers=None):

    try:

        r = requests.post(
            BASE_URL + endpoint,
            headers=headers or HEADERS,
            json=payload,
            timeout=10,
        )

        try:
            data = r.json()
        except:
            data = r.text

        log(
            title=title,
            success=(200 <= r.status_code < 300),
            response={
                "status_code": r.status_code,
                "data": data,
            }
        )

    except Exception as e:

        log(
            title=title,
            success=False,
            error=str(e)
        )


# =========================================================
# START
# =========================================================

print("\nRunning Fake AI API Tests...\n")

# =========================================================
# HEALTH
# =========================================================

test_get(
    "Health Endpoint",
    "/api/ai/v1/health"
)

# =========================================================
# INVALID TOKEN
# =========================================================

test_get(
    "Invalid Token Test",
    "/api/ai/v1/health",
    headers={
        "Authorization": "Bearer invalid_token"
    }
)

# =========================================================
# NO TOKEN
# =========================================================

test_get(
    "No Token Test",
    "/api/ai/v1/health",
    headers={}
)

# =========================================================
# CREATE STORE
# =========================================================

test_post(
    "Create Store",
    "/internal/create-store",
    {
        "name": "Coffee Lab",
        "owner": "Oktay",
        "instagram": "@coffeelab"
    }
)

# =========================================================
# CREATE PRODUCT
# =========================================================

test_post(
    "Create Product",
    "/internal/create-product",
    {
        "store_id": 1,
        "name": "Premium Mug",
        "price": 299,
        "stock": 50,
        "category": "Mugs"
    }
)

# =========================================================
# CREATE ORDER
# =========================================================

test_post(
    "Create Order",
    "/internal/create-order",
    {
        "store_id": 1,
        "item_id": 1,
        "quantity": 2
    }
)

# =========================================================
# TIMELINE
# =========================================================

test_get(
    "Timeline All",
    "/api/ai/v1/timeline?direction=asc&cursor=0"
)

# =========================================================
# TIMELINE FILTER
# =========================================================

test_get(
    "Timeline Stock Events",
    "/api/ai/v1/timeline?log_group=stock"
)

# =========================================================
# TIMELINE CURSOR
# =========================================================

test_get(
    "Timeline Cursor",
    "/api/ai/v1/timeline?direction=asc&cursor=4"
)

# =========================================================
# SUBJECT TIMELINE
# =========================================================

test_get(
    "Subject Timeline",
    "/api/ai/v1/subjects/Item/1/timeline"
)

# =========================================================
# RESOURCES DISCOVERY
# =========================================================

test_get(
    "Resources Discovery",
    "/api/ai/v1/resources"
)

# =========================================================
# GET ITEMS
# =========================================================

test_get(
    "Items List",
    "/api/ai/v1/resources/items"
)

# =========================================================
# ITEMS INCLUDE
# =========================================================

test_get(
    "Items Include Store",
    "/api/ai/v1/resources/items?include=store"
)

# =========================================================
# ITEMS SORT
# =========================================================

test_get(
    "Items Sort",
    "/api/ai/v1/resources/items?sort=-sales"
)

# =========================================================
# ITEMS SEARCH
# =========================================================

test_get(
    "Items Search",
    "/api/ai/v1/resources/items?search=Mug"
)

# =========================================================
# ITEMS FIELDS
# =========================================================

test_get(
    "Items Fields",
    "/api/ai/v1/resources/items?fields=id,name,stock"
)

# =========================================================
# ITEMS FULL QUERY
# =========================================================

test_get(
    "Items Full Query",
    "/api/ai/v1/resources/items?include=store&sort=-sales&fields=id,name,stock"
)

# =========================================================
# GET ORDERS
# =========================================================

test_get(
    "Orders List",
    "/api/ai/v1/resources/orders"
)

# =========================================================
# CREATE BANNER
# =========================================================

test_post(
    "Create Banner",
    "/api/ai/v1/banners",
    {
        "store_id": 1,
        "title": "Summer Campaign",
        "image_url": "https://example.com/banner.jpg"
    }
)

# =========================================================
# GET BANNERS
# =========================================================

test_get(
    "Get Banners",
    "/api/ai/v1/banners"
)

# =========================================================
# TOP PRODUCTS
# =========================================================

test_get(
    "Top Products",
    "/api/ai/v1/insights/products/top"
)

# =========================================================
# INVENTORY INSIGHTS
# =========================================================

test_get(
    "Inventory Insights",
    "/api/ai/v1/insights/inventory"
)

# =========================================================
# REPLAY
# =========================================================

test_get(
    "Replay Events",
    "/api/ai/v1/replay?from_cursor=1&to_cursor=10"
)

# =========================================================
# STREAM
# =========================================================

try:

    r = requests.get(
        BASE_URL + "/api/ai/v1/timeline/stream",
        headers=HEADERS,
        stream=True,
        timeout=10,
    )

    lines = []

    for line in r.iter_lines():

        if line:
            lines.append(
                json.loads(line.decode())
            )

        if len(lines) >= 3:
            break

    log(
        title="NDJSON Stream",
        success=True,
        response={
            "stream_preview": lines
        }
    )

except Exception as e:

    log(
        title="NDJSON Stream",
        success=False,
        error=str(e)
    )

# =========================================================
# LOW STOCK EVENT
# =========================================================

test_post(
    "Low Stock Trigger",
    "/internal/update-stock?item_id=1&stock=4",
)

time.sleep(1)

test_get(
    "Timeline After Low Stock",
    "/api/ai/v1/timeline?direction=desc&limit=5"
)

# =========================================================
# FINISH
# =========================================================

write_results()

print("\nAll tests completed.\n")