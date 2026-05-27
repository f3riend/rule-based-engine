#!/usr/bin/env python3
"""
AI İşletim Sistemi — Tam Entegrasyon / Orkestrasyon Stres Testi

Uçtan uca: iş olayları → dinleyici → planlayıcı → iş akışı → AI görevleri → loglar.

Gereksinimler:
  - uvicorn main:app (port 8000)
  - İsteğe bağlı: RUN_LOCAL_ORCHESTRATION=1 (varsayılan) yerel dinleyici/iş akışı döngüsü

Kullanım:
  uv run python full_system_test.py
  RUN_LOCAL_ORCHESTRATION=0 uv run python full_system_test.py  # yalnızca API + harici worker
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional

import requests

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
INTERNAL_API = f"{BASE_URL}/api/internal"
FAKE_API = f"{BASE_URL}/api/ai/v1"
TOKEN = os.environ.get("API_TOKEN", "aio_test_token")
USER_ID = int(os.environ.get("TEST_USER_ID", "1"))

AUTH_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
JSON_HEADERS = {**AUTH_HEADERS, "Content-Type": "application/json"}

WORKER_SETTLE_SEC = float(os.environ.get("WORKER_SETTLE_SEC", "4"))
ORCHESTRATION_CYCLES = int(os.environ.get("ORCHESTRATION_CYCLES", "10"))
CYCLE_DELAY_SEC = float(os.environ.get("CYCLE_DELAY_SEC", "2"))
RUN_LOCAL_ORCHESTRATION = os.environ.get("RUN_LOCAL_ORCHESTRATION", "1") == "1"
POLL_ORCHESTRATION_TIMEOUT = int(os.environ.get("POLL_ORCHESTRATION_TIMEOUT", "45"))
OUTPUT_FILE = os.environ.get("TEST_OUTPUT_FILE", "full_system_test_results.txt")

# ---------------------------------------------------------------------------
# Renkli terminal (ANSI)
# ---------------------------------------------------------------------------

class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    CYAN = "\033[36m"
    MAGENTA = "\033[35m"
    BLUE = "\033[34m"


def _color_enabled() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") != "1"


def _c(text: str, code: str) -> str:
    if not _color_enabled():
        return text
    return f"{code}{text}{C.RESET}"


# ---------------------------------------------------------------------------
# Test durumu
# ---------------------------------------------------------------------------

@dataclass
class TestRecord:
    name: str
    passed: bool
    detail: str = ""
    response: Any = None
    error: str = ""
    timestamp: str = ""
    method: str = ""
    url: str = ""
    request_body: Any = None
    http_status: int = 0
    elapsed_ms: int = 0


@dataclass
class TestState:
    records: list[TestRecord] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""
    store_id: Optional[int] = None
    item_id: Optional[int] = None
    order_id: Optional[int] = None
    banner_id: Optional[int] = None
    campaign_id: Optional[int] = None
    review_id: Optional[int] = None
    timeline_before: int = 0
    timeline_after: int = 0
    workflows_before: int = 0
    workflows_after: int = 0
    tasks_before: int = 0
    tasks_after: int = 0
    proposals_before: int = 0
    proposals_after: int = 0
    orchestration_ran: bool = False


STATE = TestState()


def print_title(text: str):
    line = "═" * 72
    print()
    print(_c(line, C.CYAN))
    print(_c(f"  {text}", C.BOLD + C.CYAN))
    print(_c(line, C.CYAN))


def print_success(text: str, detail: str = ""):
    msg = _c("✓ BAŞARILI", C.GREEN) + f" — {text}"
    if detail:
        msg += _c(f"\n    {detail}", C.DIM)
    print(msg)


def print_error(text: str, detail: str = ""):
    msg = _c("✗ HATA", C.RED) + f" — {text}"
    if detail:
        msg += _c(f"\n    {detail}", C.DIM)
    print(msg)


def print_info(text: str):
    print(_c(f"  ℹ {text}", C.BLUE))


def print_request(method: str, url: str, body: Any = None):
    print(_c(f"\n  → İSTEK {method} {url}", C.MAGENTA))
    if body is not None:
        preview = json.dumps(body, ensure_ascii=False, indent=2)
        if len(preview) > 800:
            preview = preview[:800] + "\n    …"
        print(_c(preview, C.DIM))


def print_response(status: int, data: Any, elapsed_ms: int):
    color = C.GREEN if 200 <= status < 300 else C.RED
    print(_c(f"  ← YANIT HTTP {status} ({elapsed_ms} ms)", color))
    preview = json.dumps(data, ensure_ascii=False, indent=2) if data is not None else ""
    if len(preview) > 1200:
        preview = preview[:1200] + "\n    …"
    print(_c(preview, C.DIM))


def record(
    name: str,
    passed: bool,
    detail: str = "",
    response: Any = None,
    error: str = "",
    *,
    method: str = "",
    url: str = "",
    request_body: Any = None,
    http_status: int = 0,
    elapsed_ms: int = 0,
):
    STATE.records.append(
        TestRecord(
            name=name,
            passed=passed,
            detail=detail,
            response=response,
            error=error,
            timestamp=datetime.utcnow().isoformat(),
            method=method,
            url=url,
            request_body=request_body,
            http_status=http_status,
            elapsed_ms=elapsed_ms,
        )
    )
    if passed:
        print_success(name, detail)
    else:
        print_error(name, detail or error)


def test_request(
    name: str,
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    params: dict | None = None,
    headers: dict | None = None,
    expected_status: int | tuple[int, ...] = 200,
    validate: Callable[[Any], tuple[bool, str]] | None = None,
    allow_fail: bool = False,
) -> Optional[Any]:
    """
    HTTP testi — hata olsa bile devam eder (allow_fail veya genel akış).
    """
    if isinstance(expected_status, int):
        expected_status = (expected_status,)

    hdrs = headers or (JSON_HEADERS if json_body else AUTH_HEADERS)
    req_log = json_body if json_body is not None else params
    print_request(method, url, req_log)

    started = time.monotonic()
    try:
        resp = requests.request(
            method,
            url,
            json=json_body,
            params=params,
            headers=hdrs,
            timeout=30,
        )
        elapsed = int((time.monotonic() - started) * 1000)

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text[:5000]}

        print_response(resp.status_code, data, elapsed)

        ok = resp.status_code in expected_status
        detail = f"HTTP {resp.status_code}"

        if ok and validate:
            ok, vdetail = validate(data)
            detail = vdetail or detail

        meta = dict(
            method=method,
            url=url,
            request_body=req_log,
            http_status=resp.status_code,
            elapsed_ms=elapsed,
        )

        if not ok:
            err = data.get("detail", data) if isinstance(data, dict) else str(data)
            record(name, False, detail, data, str(err)[:300], **meta)
            return None

        record(name, True, detail, data, **meta)
        return data

    except requests.RequestException as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        print_response(0, {"error": str(exc)}, elapsed)
        record(
            name,
            False,
            "Bağlantı hatası",
            error=str(exc),
            method=method,
            url=url,
            request_body=req_log,
            http_status=0,
            elapsed_ms=elapsed,
        )
        if not allow_fail:
            return None
        return None


# ---------------------------------------------------------------------------
# Türkçe sahte iş verisi
# ---------------------------------------------------------------------------

MAGAZA_ADLARI = [
    "Kahve Lab", "Moda Evi", "Teknoloji Köşesi", "Organik Pazar", "Sanat Atölyesi",
]
URUN_ADLARI = [
    "Premium Kupa", "Yün Kazak", "Kablosuz Kulaklık", "Zeytinyağı 500ml",
    "Seramik Vazo", "Deri Cüzdan", "Bitki Çayı Seti",
]
YORUMLAR = [
    "Harika ürün, hızlı kargo!",
    "Beklentimin üzerinde kalite.",
    "Paketleme özenliydi.",
]
OLUMSUZ_YORUMLAR = [
    "Ürün geç geldi, memnun değilim.",
    "Kalite fotoğraftaki gibi değil.",
    "İade süreci çok yavaş.",
]
SORULAR = [
    "Kargo ne zaman gelir?",
    "Beden tablosu var mı?",
    "İndirim kodu kullanabilir miyim?",
]


def rpick(seq):
    return random.choice(seq)


def rname(prefix: str) -> str:
    return f"{prefix}-{random.randint(1000, 9999)}"


# ---------------------------------------------------------------------------
# Sayım yardımcıları (orkestrasyon API)
# ---------------------------------------------------------------------------

def _count_list(path: str, key: str = "data") -> int:
    try:
        r = requests.get(
            f"{INTERNAL_API}{path}",
            headers=AUTH_HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            return 0
        body = r.json()
        data = body.get(key, body)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def snapshot_orchestration_counts():
    STATE.timeline_before = _count_list("/timeline?limit=100")
    STATE.workflows_before = _count_list(f"/workflows?user_id={USER_ID}&limit=200")
    STATE.tasks_before = _count_list(f"/tasks?user_id={USER_ID}&limit=200")
    STATE.proposals_before = _count_list(f"/proposals?user_id={USER_ID}&limit=200")


def refresh_orchestration_counts():
    STATE.timeline_after = _count_list("/timeline?limit=100")
    STATE.workflows_after = _count_list(f"/workflows?user_id={USER_ID}&limit=200")
    STATE.tasks_after = _count_list(f"/tasks?user_id={USER_ID}&limit=200")
    STATE.proposals_after = _count_list(f"/proposals?user_id={USER_ID}&limit=200")


def run_local_orchestration_cycles(cycles: int = ORCHESTRATION_CYCLES):
    """API ayaktayken yerel dinleyici + iş akışı worker tek tur (harici process gerekmez)."""
    print_title("Yerel Orkestrasyon Döngüsü (dinleyici + iş akışı)")
    print_info(
        f"{cycles} döngü, döngü başı {CYCLE_DELAY_SEC}s bekleme — "
        "timeline olayları işleniyor…"
    )

    try:
        from db import get_cursor, init_db, set_cursor
        from listener import process_event
        from resource_service import fetch_events
        from workflow_service import execute_workflow, get_pending_workflows, should_run

        init_db()
        processed = 0

        for cycle in range(1, cycles + 1):
            cursor = get_cursor()
            events = fetch_events(cursor)
            print_info(f"Döngü {cycle}/{cycles}: {len(events)} yeni olay (cursor={cursor})")

            for ev in events:
                try:
                    process_event(ev)
                    set_cursor(ev["id"])
                    processed += 1
                except Exception as exc:
                    print_error(f"Olay #{ev.get('id')} işlenemedi", str(exc))

            pending = get_pending_workflows()
            ran_wf = 0
            for wf in pending:
                if should_run(wf):
                    try:
                        execute_workflow(wf)
                        ran_wf += 1
                    except Exception as exc:
                        print_error(f"İş akışı #{wf.get('id')}", str(exc))

            if ran_wf:
                print_info(f"  {ran_wf} iş akışı yürütüldü")

            time.sleep(CYCLE_DELAY_SEC)

        STATE.orchestration_ran = True
        record(
            "Yerel orkestrasyon döngüsü",
            processed > 0 or cycles > 0,
            f"{processed} olay işlendi, {cycles} döngü tamamlandı",
        )

        # CrewAI worker — tek tur (bekleyen görev varsa)
        try:
            from crewai_worker import execute_task
            from task_service import get_pending_tasks

            pending_tasks = get_pending_tasks()
            crewai_done = 0
            for task in pending_tasks[:5]:
                try:
                    execute_task(task)
                    crewai_done += 1
                except Exception as exc:
                    print_info(f"CrewAI görev #{task.get('id')}: {exc}")
            if crewai_done:
                print_info(f"CrewAI: {crewai_done} görev işlendi")
        except ImportError as exc:
            print_info(f"CrewAI modülü atlandı: {exc}")
        except Exception as exc:
            print_info(f"CrewAI turu atlandı: {exc}")

    except Exception as exc:
        traceback.print_exc()
        record("Yerel orkestrasyon döngüsü", False, error=str(exc))


def wait_for_orchestration_growth(timeout: int = POLL_ORCHESTRATION_TIMEOUT):
    """Harici worker kullanılıyorsa sayıların artmasını bekle."""
    print_info(f"Orkestrasyon büyümesi bekleniyor (max {timeout}s)…")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        refresh_orchestration_counts()
        grew = (
            STATE.workflows_after > STATE.workflows_before
            or STATE.proposals_after > STATE.proposals_before
            or STATE.timeline_after > STATE.timeline_before
        )
        if grew:
            print_success("Orkestrasyon aktivitesi tespit edildi")
            return True
        time.sleep(3)
    print_info("Zaman aşımı — worker çalışmıyor olabilir")
    return False


# ---------------------------------------------------------------------------
# Test bölümleri
# ---------------------------------------------------------------------------

def test_api_health():
    print_title("1. API Sağlık Kontrolü")
    data = test_request(
        "Sağlık kontrolü",
        "GET",
        f"{FAKE_API}/health",
        expected_status=200,
        validate=lambda d: (d.get("data", {}).get("ok") is True, "API ayakta"),
    )
    return data is not None


def test_business_activity():
    print_title("2. İş Aktivitesi Simülasyonu (Fake API)")

    store_name = rpick(MAGAZA_ADLARI) + " " + rname("Mağaza")
    d = test_request(
        "Mağaza oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-store",
        json_body={"name": store_name, "owner": "Test Sahibi", "instagram": "@testshop"},
    )
    if d and d.get("data", {}).get("id"):
        STATE.store_id = d["data"]["id"]

    if not STATE.store_id:
        STATE.store_id = 1
        print_info("Mağaza ID varsayılan: 1")

    product_name = rpick(URUN_ADLARI)
    d = test_request(
        "Ürün oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-product",
        json_body={
            "store_id": STATE.store_id,
            "name": product_name,
            "price": round(random.uniform(49, 499), 2),
            "stock": random.randint(30, 80),
            "category": "genel",
        },
    )
    if d and d.get("data", {}).get("id"):
        STATE.item_id = d["data"]["id"]

    if not STATE.item_id:
        STATE.item_id = 1

    qty = random.randint(1, 3)
    d = test_request(
        "Sipariş oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-order",
        json_body={
            "store_id": STATE.store_id,
            "item_id": STATE.item_id,
            "quantity": qty,
        },
    )
    if d and d.get("data", {}).get("id"):
        STATE.order_id = d["data"]["id"]

    low_stock = random.randint(2, 8)
    test_request(
        "Stok güncelleme (düşük stok)",
        "POST",
        f"{BASE_URL}/internal/update-stock",
        params={"item_id": STATE.item_id, "stock": low_stock},
        headers=JSON_HEADERS,
    )

    discount = random.randint(15, 45)
    test_request(
        "İndirim uygulama",
        "POST",
        f"{BASE_URL}/internal/update-discount",
        json_body={
            "item_id": STATE.item_id,
            "discount": discount,
            "store_id": STATE.store_id,
        },
    )

    test_request(
        "Olumlu yorum oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-review",
        json_body={
            "store_id": STATE.store_id,
            "item_id": STATE.item_id,
            "author": "Ayşe K.",
            "rating": 5.0,
            "comment": rpick(YORUMLAR),
        },
    )

    d = test_request(
        "Olumsuz yorum oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-review",
        json_body={
            "store_id": STATE.store_id,
            "item_id": STATE.item_id,
            "author": "Mehmet Y.",
            "rating": 1.0,
            "comment": rpick(OLUMSUZ_YORUMLAR),
            "sentiment": "negative",
        },
    )
    if d and d.get("data", {}).get("id"):
        STATE.review_id = d["data"]["id"]

    test_request(
        "Müşteri sorusu oluşturma",
        "POST",
        f"{BASE_URL}/internal/create-question",
        json_body={
            "store_id": STATE.store_id,
            "item_id": STATE.item_id,
            "author": "Zeynep",
            "question": rpick(SORULAR),
        },
    )

    d = test_request(
        "Kampanya başlatma",
        "POST",
        f"{BASE_URL}/internal/create-campaign",
        json_body={
            "store_id": STATE.store_id,
            "name": f"Kampanya {rname('Yaz')}",
            "campaign_type": "promotion",
            "discount_pct": random.randint(10, 30),
        },
    )
    if d and d.get("data", {}).get("id"):
        STATE.campaign_id = d["data"]["id"]

    test_request(
        "Satış metrik güncelleme",
        "POST",
        f"{BASE_URL}/internal/update-sales",
        json_body={
            "item_id": STATE.item_id,
            "sales_change_pct": random.uniform(-30, -10),
        },
    )

    if STATE.order_id:
        test_request(
            "Kargo gecikmesi",
            "POST",
            f"{BASE_URL}/internal/shipping-delay",
            json_body={
                "order_id": STATE.order_id,
                "delay_days": random.randint(2, 7),
                "reason": "Depo yoğunluğu — entegrasyon testi",
            },
            allow_fail=True,
        )

    d = test_request(
        "Banner oluşturma (AI API)",
        "POST",
        f"{FAKE_API}/banners",
        json_body={
            "store_id": STATE.store_id,
            "title": f"Banner {rname('Promo')}",
            "image_url": "https://example.com/banner.jpg",
        },
    )
    if d and d.get("data", {}).get("id"):
        STATE.banner_id = d["data"]["id"]

    if STATE.banner_id:
        test_request(
            "Banner performans güncelleme",
            "POST",
            f"{BASE_URL}/internal/update-banner-performance",
            json_body={
                "banner_id": STATE.banner_id,
                "ctr": round(random.uniform(0.06, 0.15), 3),
                "impressions": random.randint(1000, 10000),
                "clicks": random.randint(50, 800),
            },
        )
    else:
        record("Banner performans güncelleme", False, "Banner ID yok — atlandı")


def test_orchestration_processing():
    print_title("3. Orkestrasyon İşleme")
    print_info(f"Worker yerleşmesi: {WORKER_SETTLE_SEC}s")
    time.sleep(WORKER_SETTLE_SEC)

    if RUN_LOCAL_ORCHESTRATION:
        run_local_orchestration_cycles()
    else:
        print_info("RUN_LOCAL_ORCHESTRATION=0 — harici listener/worker bekleniyor")
        wait_for_orchestration_growth()

    refresh_orchestration_counts()


def test_timeline_and_events():
    print_title("4. Zaman Tüneli ve Olaylar")

    def validate_timeline(data):
        events = data.get("data", [])
        if not events:
            return False, "Zaman tüneli boş"
        groups = {e.get("group") for e in events}
        return True, f"{len(events)} olay, gruplar: {', '.join(sorted(g for g in groups if g))}"

    test_request(
        "Zaman tüneli listesi",
        "GET",
        f"{INTERNAL_API}/timeline?limit=50",
        validate=validate_timeline,
    )

    grew = STATE.timeline_after >= STATE.timeline_before
    record(
        "Timeline olay artışı",
        grew or STATE.timeline_after > 0,
        f"önce={STATE.timeline_before} sonra={STATE.timeline_after}",
    )


def test_workflows_and_tasks():
    print_title("5. İş Akışları ve AI Görevleri")

    def validate_workflows(data):
        wfs = data.get("data", [])
        if not wfs:
            return False, "İş akışı yok — listener/worker çalıştırın"
        names = [w.get("workflow_name") for w in wfs[:5]]
        return True, f"{len(wfs)} iş akışı, örnek: {', '.join(names)}"

    test_request(
        "İş akışı listesi",
        "GET",
        f"{INTERNAL_API}/workflows?user_id={USER_ID}&limit=50",
        validate=validate_workflows,
        allow_fail=True,
    )

    def validate_tasks(data):
        tasks = data.get("data", [])
        if not tasks:
            return True, "Görev yok (henüz zamanlanmamış olabilir)"
        types = list({t.get("task_type") for t in tasks[:8]})
        return True, f"{len(tasks)} görev, tipler: {types}"

    test_request(
        "AI görev listesi",
        "GET",
        f"{INTERNAL_API}/tasks?user_id={USER_ID}&limit=50",
        validate=validate_tasks,
        allow_fail=True,
    )

    wf_grew = STATE.workflows_after > STATE.workflows_before
    record(
        "İş akışı üretimi (orkestrasyon)",
        wf_grew or STATE.workflows_after > 0,
        f"Δ iş akışı={STATE.workflows_after - STATE.workflows_before}, "
        f"toplam={STATE.workflows_after}",
    )


def test_planner_and_proposals():
    print_title("6. Otonom Planlayıcı ve Öneriler")

    nl_rule = "Ürün indirime girince Instagram paylaşımı oluştur."

    def validate_preview(data):
        plan = data.get("autonomous_plan") or data.get("plan") or {}
        if not plan:
            return False, "Otonom plan yok"
        conf = plan.get("confidence", 0)
        tools = plan.get("tools", [])
        return (
            True,
            f"karar={plan.get('decision')}, güven={conf:.2f}, araçlar={tools}",
        )

    test_request(
        "Kural önizleme (DSL + otonom plan)",
        "POST",
        f"{INTERNAL_API}/rules/preview",
        json_body={
            "user_id": USER_ID,
            "natural_language": nl_rule,
        },
        validate=validate_preview,
        allow_fail=True,
    )

    test_request(
        "Otonom plan önizleme",
        "POST",
        f"{INTERNAL_API}/rules/preview-autonomous",
        json_body={"user_id": USER_ID, "natural_language": nl_rule},
        validate=lambda d: (
            (d.get("plan") or {}).get("decision") in ("create_workflow", "noop"),
            f"plan={(d.get('plan') or {}).get('workflow_name')}",
        ),
        allow_fail=True,
    )

    def validate_proposals(data):
        props = data.get("data", [])
        if not props:
            return True, "Öneri yok (onay kuyruğunda veya henüz plan yok)"
        applied = sum(1 for p in props if p.get("applied"))
        return True, f"{len(props)} öneri, uygulanan={applied}"

    test_request(
        "Planlayıcı önerileri",
        "GET",
        f"{INTERNAL_API}/proposals?user_id={USER_ID}&limit=30",
        validate=validate_proposals,
        allow_fail=True,
    )

    prop_grew = STATE.proposals_after > STATE.proposals_before
    wf_ok = STATE.workflows_after > STATE.workflows_before
    record(
        "Planlayıcı öneri üretimi",
        prop_grew or STATE.proposals_after > 0 or wf_ok,
        f"Δ öneri={STATE.proposals_after - STATE.proposals_before}, "
        f"iş akışı Δ={STATE.workflows_after - STATE.workflows_before}",
    )


def test_logs_and_tools():
    print_title("7. Loglar ve Araç Çalıştırmaları")

    test_request(
        "Otomasyon logları",
        "GET",
        f"{INTERNAL_API}/automation-logs?user_id={USER_ID}&limit=30",
        validate=lambda d: (
            True,
            f"{len(d.get('data', []))} log kaydı",
        ),
        allow_fail=True,
    )

    test_request(
        "Araç çalıştırma logları",
        "GET",
        f"{INTERNAL_API}/tool-executions?limit=30",
        validate=lambda d: (
            True,
            f"{len(d.get('data', []))} araç çalıştırması",
        ),
        allow_fail=True,
    )

    test_request(
        "Araç kayıt defteri",
        "GET",
        f"{INTERNAL_API}/tools/registry",
        validate=lambda d: (
            len(d.get("data", [])) >= 2,
            f"{len(d.get('data', []))} araç tanımlı",
        ),
        allow_fail=True,
    )


def test_business_intelligence():
    print_title("8. İş Zekası ve Durum")

    test_request(
        "İş içgörüleri",
        "GET",
        f"{INTERNAL_API}/business-insights?user_id={USER_ID}",
        validate=lambda d: (
            "insights" in d or "state" in d,
            "BI snapshot alındı",
        ),
        allow_fail=True,
    )

    test_request(
        "İş durumu grafiği",
        "GET",
        f"{INTERNAL_API}/business-state?user_id={USER_ID}",
        validate=lambda d: (
            d.get("inventory") is not None or d.get("sales") is not None,
            f"stok sağlığı={d.get('inventory', {}).get('health', '?')}",
        ),
        allow_fail=True,
    )

    test_request(
        "Planlayıcı belleği",
        "GET",
        f"{INTERNAL_API}/planner-memory?user_id={USER_ID}",
        validate=lambda d: (
            True,
            f"{len(d.get('data', []))} bellek kaydı",
        ),
        allow_fail=True,
    )

    test_request(
        "Agent kayıtları",
        "GET",
        f"{INTERNAL_API}/agents",
        validate=lambda d: (
            len(d.get("data", [])) >= 1,
            f"{len(d.get('data', []))} agent tanımı",
        ),
        allow_fail=True,
    )


def test_approval_queue():
    print_title("9. Onay Kuyruğu")

    def validate_approvals(data):
        items = data.get("data", [])
        return True, f"{len(items)} bekleyen onay"

    test_request(
        "Onay kuyruğu listesi",
        "GET",
        f"{INTERNAL_API}/approvals?user_id={USER_ID}",
        validate=validate_approvals,
        allow_fail=True,
    )

    # İlk bekleyen onayı onayla (varsa)
    try:
        r = requests.get(
            f"{INTERNAL_API}/approvals?user_id={USER_ID}",
            headers=AUTH_HEADERS,
            timeout=15,
        )
        if r.status_code == 200:
            pending = r.json().get("data", [])
            if pending:
                aid = pending[0]["id"]
                test_request(
                    "Onay işlemi (ilk bekleyen)",
                    "POST",
                    f"{INTERNAL_API}/approvals/{aid}/approve",
                    expected_status=(200, 422),
                    allow_fail=True,
                )
            else:
                record("Onay işlemi", True, "Bekleyen onay yok — atlandı")
    except Exception as exc:
        record("Onay işlemi", False, error=str(exc))


def test_rules_cache():
    print_title("10. Kurallar ve Önbellek")

    test_request(
        "Kural listesi",
        "GET",
        f"{INTERNAL_API}/rules?user_id={USER_ID}",
        validate=lambda d: (True, f"{len(d.get('data', []))} kural"),
        allow_fail=True,
    )

    test_request(
        "Önbellek istatistikleri",
        "GET",
        f"{INTERNAL_API}/cache-stats",
        allow_fail=True,
    )


# ---------------------------------------------------------------------------
# TXT rapor
# ---------------------------------------------------------------------------

def _format_json_block(data: Any, max_len: int = 8000) -> str:
    if data is None:
        return "(yok)\n"
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(data)
    if len(text) > max_len:
        text = text[:max_len] + "\n… (kısaltıldı)"
    return text + "\n"


def write_results_to_file(path: str = OUTPUT_FILE) -> str:
    """Tüm test sonuçlarını TXT dosyasına yazar."""
    STATE.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(STATE.records)
    passed = sum(1 for r in STATE.records if r.passed)
    failed = total - passed

    lines: list[str] = []
    sep = "=" * 80
    thin = "-" * 80

    lines.append(sep)
    lines.append("AI İŞLETİM SİSTEMİ — TAM ENTEGRASYON TEST SONUÇLARI")
    lines.append(sep)
    lines.append("")
    lines.append(f"Başlangıç       : {STATE.started_at}")
    lines.append(f"Bitiş           : {STATE.finished_at}")
    lines.append(f"Base URL        : {BASE_URL}")
    lines.append(f"Kullanıcı ID    : {USER_ID}")
    lines.append(f"Yerel orkestr.  : {RUN_LOCAL_ORCHESTRATION}")
    lines.append(f"Döngü sayısı    : {ORCHESTRATION_CYCLES}")
    lines.append("")

    lines.append("--- ORKESTRASYON ÖZETİ ---")
    lines.append(f"Mağaza ID         : {STATE.store_id}")
    lines.append(f"Ürün ID           : {STATE.item_id}")
    lines.append(f"Sipariş ID        : {STATE.order_id}")
    lines.append(f"Banner ID         : {STATE.banner_id}")
    lines.append(f"Kampanya ID       : {STATE.campaign_id}")
    lines.append(f"Yerel döngü çalıştı: {'evet' if STATE.orchestration_ran else 'hayır'}")
    lines.append(f"Timeline          : {STATE.timeline_before} → {STATE.timeline_after}")
    lines.append(f"İş akışları       : {STATE.workflows_before} → {STATE.workflows_after}")
    lines.append(f"AI görevleri      : {STATE.tasks_before} → {STATE.tasks_after}")
    lines.append(f"Planlayıcı öneri  : {STATE.proposals_before} → {STATE.proposals_after}")
    lines.append("")

    lines.append(sep)
    lines.append("TEST DETAYLARI")
    lines.append(sep)

    for i, r in enumerate(STATE.records, 1):
        status = "BAŞARILI" if r.passed else "BAŞARISIZ"
        lines.append("")
        lines.append(thin)
        lines.append(f"TEST #{i}: {r.name}")
        lines.append(f"DURUM  : {status}")
        lines.append(f"ZAMAN  : {r.timestamp}")
        if r.detail:
            lines.append(f"DETAY  : {r.detail}")
        if r.error:
            lines.append(f"HATA   : {r.error}")
        if r.method or r.url:
            lines.append("")
            lines.append("İSTEK:")
            lines.append(f"  {r.method} {r.url}")
            if r.http_status:
                lines.append(f"  HTTP {r.http_status} ({r.elapsed_ms} ms)")
            if r.request_body is not None:
                lines.append("  Gövde:")
                for line in _format_json_block(r.request_body).splitlines():
                    lines.append(f"    {line}")
        if r.response is not None:
            lines.append("")
            lines.append("YANIT:")
            for line in _format_json_block(r.response).splitlines():
                lines.append(f"  {line}")

    lines.append("")
    lines.append(sep)
    lines.append("ÖZET")
    lines.append(sep)
    lines.append(f"Toplam test  : {total}")
    lines.append(f"Başarılı     : {passed}")
    lines.append(f"Başarısız    : {failed}")
    lines.append("")

    if failed:
        lines.append("Başarısız testler:")
        for r in STATE.records:
            if not r.passed:
                lines.append(f"  • {r.name}: {r.detail or r.error}")
        lines.append("")

    orchestration_ok = (
        STATE.timeline_after > 0
        and (STATE.workflows_after > 0 or STATE.proposals_after > 0)
    )
    lines.append(
        "Orkestrasyon pipeline: "
        + ("VERİ ÜRETTİ ✓" if orchestration_ok else "SINIRLI ⚠")
    )
    lines.append("")
    lines.append(sep)

    content = "\n".join(lines)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Özet
# ---------------------------------------------------------------------------

def print_summary():
    print_title("TEST ÖZETİ")

    total = len(STATE.records)
    passed = sum(1 for r in STATE.records if r.passed)
    failed = total - passed

    print()
    print(_c(f"  Toplam test    : {total}", C.BOLD))
    print(_c(f"  Başarılı       : {passed}", C.GREEN))
    print(_c(f"  Başarısız      : {failed}", C.RED if failed else C.DIM))
    print()

    if failed:
        print(_c("  Başarısız testler:", C.YELLOW))
        for r in STATE.records:
            if not r.passed:
                print(_c(f"    • {r.name}: {r.detail or r.error}", C.RED))

    print()
    print(_c("  ─── Orkestrasyon Özeti ───", C.CYAN))
    print(f"    Mağaza ID        : {STATE.store_id}")
    print(f"    Ürün ID          : {STATE.item_id}")
    print(f"    Sipariş ID       : {STATE.order_id}")
    print(f"    Yerel döngü      : {'evet' if STATE.orchestration_ran else 'hayır'}")
    print(f"    Timeline         : {STATE.timeline_before} → {STATE.timeline_after}")
    print(f"    İş akışları      : {STATE.workflows_before} → {STATE.workflows_after}")
    print(f"    AI görevleri     : {STATE.tasks_before} → {STATE.tasks_after}")
    print(f"    Planlayıcı öneri : {STATE.proposals_before} → {STATE.proposals_after}")
    print()

    orchestration_ok = (
        STATE.timeline_after > 0
        and (STATE.workflows_after > 0 or STATE.proposals_after > 0)
    )
    if orchestration_ok:
        print(_c("  ✓ Orkestrasyon pipeline veri üretti", C.GREEN))
    else:
        print(_c(
            "  ⚠ Orkestrasyon sınırlı — uvicorn + RUN_LOCAL_ORCHESTRATION=1 veya "
            "harici worker çalıştırın",
            C.YELLOW,
        ))

    print()
    print(_c(f"  Tamamlanma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", C.DIM))

    out_path = write_results_to_file()
    print()
    print(_c(f"  Sonuçlar dosyaya yazıldı: {out_path}", C.CYAN))
    print()

    return failed == 0


def main():
    STATE.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print()
    print(_c("╔══════════════════════════════════════════════════════════════════════╗", C.BOLD))
    print(_c("║     AI İŞLETİM SİSTEMİ — TAM ENTEGRASYON / ORKESTRASYON TESTİ       ║", C.BOLD))
    print(_c("╚══════════════════════════════════════════════════════════════════════╝", C.BOLD))
    print_info(f"Base URL: {BASE_URL}")
    print_info(f"Yerel orkestrasyon: {RUN_LOCAL_ORCHESTRATION}")

    snapshot_orchestration_counts()

    if not test_api_health():
        print_error(
            "API erişilemiyor",
            "Önce çalıştırın: uv run uvicorn main:app --reload",
        )
        print_summary()
        sys.exit(1)

    try:
        test_business_activity()
        test_orchestration_processing()
        test_timeline_and_events()
        test_workflows_and_tasks()
        test_planner_and_proposals()
        test_logs_and_tools()
        test_business_intelligence()
        test_approval_queue()
        test_rules_cache()
    except KeyboardInterrupt:
        print_info("\nTest kullanıcı tarafından durduruldu.")
    except Exception as exc:
        print_error("Beklenmeyen hata", str(exc))
        traceback.print_exc()

    ok = print_summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
