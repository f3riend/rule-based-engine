"""
LangGraph node implementations.

Her node aynı imzaya sahip: `(state: RuleExecutionState) -> dict`. Dönüşler
mevcut state ile reducer'lar üzerinden birleştirilir. Hiçbir node doğrudan
state'i mutate etmez — return ile partial update verir.

Genel desen:
    1. trace start kaydı oluştur
    2. node işini yap (Pydantic validation içeren tool çağrıları, vb.)
    3. trace ok/failed kaydı oluştur
    4. partial state döndür

Hata durumunda: status="failed", last_error doldurulur, ama node exception
fırlatmaz — graph'ın kontrolünü kaybetmememiz gerekiyor.

NOT: approval_gate_node işin doğası gereği "no-op pre-interrupt" şeklinde
çalışır. LangGraph compile çağrısı bu node'u interrupt_before=[...] ile
işaretler — graph node'u çalıştırmadan ÖNCE duraklar. Operatör onay verince
graph state.approval.decision güncellenmiş olarak resume edilir, node ondan
sonra çalıştırılır ve karar yoluna göre branch eder.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from typing import Any

from langgraph_engine.state import (
    ApprovalDecision,
    EventContext,
    GeneratedContent,
    MonitorResult,
    PublishResult,
    RiskAssessment,
    RuleExecutionState,
    make_trace,
)


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _rule_from_state(state: RuleExecutionState) -> dict:
    return state.get("rule") or {}


def _content_template(state: RuleExecutionState) -> str:
    return ((state.get("rule") or {}).get("content") or {}).get("template", "generic")


def _channel(state: RuleExecutionState) -> str:
    return ((state.get("rule") or {}).get("content") or {}).get("channel", "instagram")


def _action_config(state: RuleExecutionState, kind: str) -> dict:
    for a in (state.get("rule") or {}).get("actions", []):
        if a.get("kind") == kind:
            return a.get("config") or {}
    return {}


def _emit(tag: str, payload: dict, *, user_id: int | None = None):
    """observability._emit'e güvenli wrapper."""
    try:
        from observability import _emit as oemit
        oemit(tag, payload, persist=True, user_id=user_id)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Node: supervisor — graph girişinde context'i hazırla
# ---------------------------------------------------------------------------


def supervisor_node(state: RuleExecutionState) -> dict:
    """Tüm graph'ın "giriş" node'u. State'i log'lar, mevcut current_node'u
    siler, trace event başlatır.
    """
    t0 = time.monotonic()
    rule = _rule_from_state(state)
    event = state.get("event") or {}
    summary = (
        f"Kural #{state.get('rule_id')} tetiklendi: "
        f"{rule.get('name', '—')} (olay: {event.get('event_type')})"
    )
    _emit("RULE_EXECUTION_START", {
        "rule_id": state.get("rule_id"),
        "execution_id": state.get("execution_id"),
        "event_id": event.get("event_id"),
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "supervisor",
        "status": "running",
        "trace_events": [make_trace(
            "supervisor", "ok", summary,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: wait — gecikme talep edildi
# ---------------------------------------------------------------------------


def wait_node(state: RuleExecutionState) -> dict:
    """Gecikme zamanı geldi mi kontrol et — Tur 2: gerçek duraklat/resume.

    Davranış:
        - delay <= 0  → hemen devam et.
        - metadata.wait_resolved == True (resume_after_wait set etti) →
          süre dolmuş, hemen devam et.
        - Aksi halde: scheduled_entry oluştur (workflow_worker
          fire_due_schedules → resume_after_wait çağıracak),
          status='waiting_timer' yap, graph akışını DURAKLAT
          (LangGraph END'e gider, runtime row'u waiting_timer kabul eder).

    workflow_worker._handle_wait_resumes() entry'yi tetiklediğinde
    runtime.resume_after_wait() çağrılır, state.metadata.wait_resolved=True
    set edilir ve graph.invoke(None) ile bu node'a tekrar gelinir; bu sefer
    geçer.
    """
    t0 = time.monotonic()
    cfg = _action_config(state, "wait")
    delay = int(cfg.get("delay_seconds") or
                (state.get("rule") or {}).get("timing", {}).get("delay_seconds", 0))

    # Resume durumu — wait süresi dolmuş.
    if (state.get("metadata") or {}).get("wait_resolved"):
        return {
            "current_node": "wait",
            "status": "running",
            "trace_events": [make_trace(
                "wait", "ok", "Bekleme süresi doldu, akış devam ediyor.",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )],
        }

    # Hiç bekleme gerekmiyorsa direkt geç.
    if delay <= 0:
        return {
            "current_node": "wait",
            "trace_events": [make_trace(
                "wait", "ok", "Bekleme yok, akış devam ediyor.",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )],
        }

    fire_at = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
    summary = (
        f"Bu kural {_humanize(delay)} sonra ({fire_at}) devam edecek "
        f"— graph duraklatıldı, planlama oluşturuldu."
    )

    # Scheduling_service'e fire entry — workflow_worker'ın görüp resume
    # çağıracağı tetik. payload.resume_after_wait=True işareti kritik.
    try:
        from scheduling_service import create_schedule
        create_schedule(
            user_id=state.get("user_id") or 1,
            kind="workflow",
            scheduled_at=fire_at,
            title=f"Kural #{state.get('rule_id')} devamı",
            description=summary,
            workflow_name=f"rule_resume_{state.get('rule_id')}_{state.get('execution_id')}",
            payload={
                "execution_id": state.get("execution_id"),
                "thread_id": state.get("thread_id"),
                "resume_after_wait": True,
            },
        )
    except Exception as exc:
        print(f"[NODE wait] schedule create failed: {exc}")

    # State'i waiting_timer yap — runtime.start_execution bunu görüp
    # rule_executions tablosunda status='waiting_timer' set eder ve
    # graph'ı bu node'da bırakır.
    return {
        "current_node": "wait",
        "status": "waiting_timer",
        "metadata": {"resume_at": fire_at, "wait_delay_seconds": delay,
                     "wait_resolved": False},
        "trace_events": [make_trace(
            "wait", "interrupted", summary,
            details={"delay_seconds": delay, "resume_at": fire_at},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


def _humanize(s: int) -> str:
    if s < 60:
        return f"{s} saniye"
    if s < 3600:
        return f"{s//60} dakika"
    if s < 86400:
        return f"{s//3600} saat"
    return f"{s//86400} gün"


# ---------------------------------------------------------------------------
# Node: content_generator
# ---------------------------------------------------------------------------


_TEMPLATE_HEADLINES: dict[str, tuple[str, str]] = {
    "anneler_gunu":  ("Anneler Günü’ne özel", "Sevgisini hep yanında hisset"),
    "babalar_gunu":  ("Babalar Günü", "Hayatımızın kahramanlarına"),
    "yilbasi":       ("Yeni yıla özel", "Yeni başlangıçlar, yeni indirimler"),
    "ramazan":       ("Ramazan özel", "Bereketli günlere yakışır seçkiler"),
    "kurban_bayrami":("Kurban Bayramı’na özel", "Bayram coşkusu indirime dönüştü"),
    "yaz_indirim":   ("Yaz İndirimi", "Yaz sezonu fırsatları seni bekliyor"),
    "kis_indirim":   ("Kış İndirimi", "Soğuk havada sıcacık fırsatlar"),
    "kara_cuma":     ("Kara Cuma", "Yılın en büyük indirim günü"),
    "yeni_urun_lansman": ("Yeni Ürün", "Tanıtmaktan heyecan duyduğumuz yeniliğimiz"),
    "magaza_acilis":("Mağazamız Açıldı", "İlk müşterilerimize özel hoş geldin fırsatları"),
    "tesekkur":      ("Teşekkürler", "Sizinle olmak güzel"),
    "ozur":          ("Özür dileriz", "Yaşananları telafi etmek için buradayız"),
    "ozel_indirim":  ("Özel İndirim", "Sadece sana özel bir fırsat"),
    "generic":       ("Yeni paylaşım", "Sizler için hazırlandı"),
}


def content_generator_node(state: RuleExecutionState) -> dict:
    """Şablon ve event bağlamından içerik üret.

    Mevcut tool registry'yi (tools.py, BannerGeneratorTool/InstagramCampaignTool)
    CrewAI BaseTool olarak yüklü ama biz doğrudan ._run() çağırıyoruz —
    çalışma için CrewAI runtime'ı gerekmiyor.
    """
    t0 = time.monotonic()
    template = _content_template(state)
    channel = _channel(state)

    headline, body = _TEMPLATE_HEADLINES.get(template, _TEMPLATE_HEADLINES["generic"])
    rule_meta = _rule_from_state(state)
    event = state.get("event") or {}

    # Hedef hesap adı varsa onu da işle
    handle = ((rule_meta.get("target") or {}).get("account_handle"))
    entity_name = (
        (event.get("item") or {}).get("name")
        or (event.get("store") or {}).get("name")
        or ""
    )
    if entity_name:
        body = f"{body} — {entity_name}"

    hashtags = []
    if template != "generic":
        # Şablona göre hashtag öner
        hashtags = {
            "anneler_gunu":   ["AnnelerGünü", "AnneSevgisi"],
            "babalar_gunu":   ["BabalarGünü"],
            "yilbasi":        ["YeniYıl", "Yılbaşı"],
            "ramazan":        ["Ramazan"],
            "kara_cuma":      ["KaraCuma", "BlackFriday"],
            "yaz_indirim":    ["YazIndirimi", "Sezon"],
            "kis_indirim":    ["KısIndirimi"],
            "yeni_urun_lansman": ["YeniÜrün", "Lansman"],
            "magaza_acilis":  ["YeniMağaza", "HoşGeldiniz"],
        }.get(template, [])

    content = GeneratedContent(
        channel=channel,
        template=template,
        headline=headline,
        body=body,
        caption=f"{headline} — {body}",
        hashtags=hashtags,
        image_prompt=f"{template} temalı sosyal medya görseli, {channel} formatı",
    )

    summary = f"İçerik üretildi: {headline} — kanal {channel}, şablon {template}."
    _emit("CONTENT_GENERATED", {
        "execution_id": state.get("execution_id"),
        "template": template, "channel": channel,
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "content_generator",
        "content": content.model_dump(),
        "trace_events": [make_trace(
            "content_generator", "ok", summary,
            details={"template": template, "channel": channel},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: risk_analyzer
# ---------------------------------------------------------------------------


_RISKY_WORDS = (
    "tıbbi", "ilaç", "hasta", "tedavi", "garanti", "kesinlikle",
    "sınırsız", "para iadesi", "geri ödeme", "yasal",
    "free money", "guarantee", "cure",
)


def risk_analyzer_node(state: RuleExecutionState) -> dict:
    """Üretilen içeriği + eylem türünü risk açısından değerlendir.

    Heuristik: dış yayın + duyarlı keyword + olumsuz event geçmişi → risk
    skoru yüksek.
    """
    t0 = time.monotonic()
    content = state.get("content") or {}
    text = " ".join([
        content.get("headline", ""),
        content.get("body", ""),
        content.get("caption", ""),
    ]).lower()

    flags: list[str] = []
    score = 0.0

    for word in _RISKY_WORDS:
        if word in text:
            flags.append(f"risky_word:{word}")
            score += 0.15

    channel = content.get("channel") or _channel(state)
    if channel in ("instagram", "facebook"):
        score += 0.2          # dış yayın baseline
        flags.append("external_publish")

    # Olumsuz event tipiyle yayın yapmak da risk artırır
    event_type = (state.get("event") or {}).get("event_type", "")
    if event_type in ("review.negative", "shipping.delayed", "store.rejected"):
        score += 0.25
        flags.append(f"sensitive_event:{event_type}")

    score = min(1.0, score)
    level = "high" if score >= 0.55 else ("medium" if score >= 0.3 else "low")
    requires_human = level in ("medium", "high")

    explanation = "; ".join(flags) if flags else "Belirgin risk sinyali yok."

    risk = RiskAssessment(
        risk_level=level,
        risk_score=score,
        flags=flags,
        requires_human=requires_human,
        explanation=explanation,
    )

    summary = f"Risk seviyesi: {level} (skor {score:.2f}). {explanation[:120]}"
    _emit("RISK_ASSESSED", {
        "execution_id": state.get("execution_id"),
        "risk_level": level, "score": score, "flags": flags,
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "risk_analyzer",
        "risk": risk.model_dump(),
        "trace_events": [make_trace(
            "risk_analyzer",
            "ok" if level != "high" else "ok",
            summary,
            details={"flags": flags, "score": score},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: approval_gate
# ---------------------------------------------------------------------------


def approval_gate_node(state: RuleExecutionState) -> dict:
    """Onay node'u. interrupt_before ile compile edilir, dolayısıyla
    LangGraph bu node'u çalıştırmadan ÖNCE duraklar. Resume sırasında
    state.approval.decision güncel olur ve buraya tekrar girilir.

    Burada yaptığımız: approval row'unu oluştur (eğer yoksa) ve karar
    durumunu state'e yansıt. Karar yoksa interrupt zaten devreyi
    durdurur — bu node'un kodu çağrılmaz.
    """
    t0 = time.monotonic()

    existing = state.get("approval") or {}
    if existing.get("decision") in ("approved", "rejected", "edited"):
        summary = f"Onay kararı alındı: {existing.get('decision')}"
        _emit("APPROVAL_RESOLVED", {
            "execution_id": state.get("execution_id"),
            "decision": existing.get("decision"),
            "summary": summary,
        }, user_id=state.get("user_id"))
        return {
            "current_node": "approval_gate",
            "trace_events": [make_trace(
                "approval_gate", "ok", summary,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )],
        }

    # Karar yoksa: approval request oluştur ve "waiting_human" işaretle.
    # Bu code path normalde ulaşılmaz çünkü graph interrupt_before ile
    # duruyor, ama tetik anında approval row'u kurmak gerek.
    try:
        from approval_service import create_approval_request

        proposal = {
            "decision": "create_workflow",
            "workflow_name": f"rule_{state.get('rule_id')}_exec_{state.get('execution_id')}",
            "reason": (state.get("rule") or {}).get("name", "AI önerisi"),
            "tools": [],
            "priority": "high" if (state.get("risk") or {}).get("risk_level") == "high" else "medium",
            "confidence": 1.0 - float((state.get("risk") or {}).get("risk_score") or 0),
            "requires_approval": True,
            "business_intent": "structured_rule_execution",
            "task_payload": {
                "execution_id": state.get("execution_id"),
                "thread_id": state.get("thread_id"),
                "content": state.get("content"),
                "risk": state.get("risk"),
            },
            "entity_type": "rule_execution",
            "entity_id": state.get("execution_id"),
        }
        approval_id = create_approval_request(
            user_id=state.get("user_id") or 1,
            proposal=proposal,
            event_id=(state.get("event") or {}).get("event_id"),
        )
    except Exception as exc:
        approval_id = None
        print(f"[NODE approval_gate] create_approval_request failed: {exc}")

    summary = "İnsan onayı bekleniyor."
    _emit("APPROVAL_REQUESTED", {
        "execution_id": state.get("execution_id"),
        "approval_id": approval_id,
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "approval_gate",
        "status": "waiting_human",
        "approval": ApprovalDecision(
            approval_id=approval_id, decision="pending"
        ).model_dump(),
        "trace_events": [make_trace(
            "approval_gate", "interrupted", summary,
            details={"approval_id": approval_id},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: publisher
# ---------------------------------------------------------------------------


def publisher_node(state: RuleExecutionState) -> dict:
    """İçeriği seçilen kanala "yayınla". Şu an gerçek API çağrısı yok —
    InstagramCampaignTool ile aynı mantık: credential varsa
    REAL_PUBLISH_WOULD_HAPPEN, yoksa draft.
    """
    t0 = time.monotonic()

    if state.get("status") == "waiting_human":
        # Sanırım approval interrupt sonrası status="running"a güncellenmedi.
        # Defensive: burada running'e geri al.
        pass

    approval = state.get("approval") or {}
    if approval.get("decision") == "rejected":
        msg = "Yayın reddedildi; akış iptal ediliyor."
        return {
            "current_node": "publisher",
            "status": "cancelled",
            "publish": PublishResult(
                success=False, message=msg,
                channel=_channel(state),
            ).model_dump(),
            "trace_events": [make_trace(
                "publisher", "ok", msg,
                duration_ms=int((time.monotonic() - t0) * 1000),
            )],
        }

    content = state.get("content") or {}
    channel = content.get("channel") or _channel(state)

    # Credential layer'ı kontrol et + adapter (Tur 2)
    cred_id, handle, mode = None, None, "draft_only"
    adapter_attempt: dict | None = None
    user_id = state.get("user_id") or 1
    if channel in ("instagram", "facebook", "tiktok"):
        try:
            from social_credentials import try_get_credential
            cred = try_get_credential(user_id, channel)
            if cred is not None:
                cred_id = cred.id
                handle = cred.account_handle
                mode = "real_publish_would_happen"

                # Real adapter çağrısını DENE — SOCIAL_PUBLISH_LIVE
                # açıksa gerçek HTTP'ye yaklaşır; kapalıysa
                # FeatureDisabledError fırlatır ve fake'e geri döner.
                try:
                    from tool_adapters import (
                        AdapterCredentialError, FeatureDisabledError, get_adapter,
                    )
                    adapter = get_adapter(channel)
                    if adapter is not None:
                        try:
                            adapter_attempt = adapter.publish_post(
                                user_id=user_id,
                                account_handle=cred.account_handle,
                                caption=f"{content.get('headline','')} — {content.get('body','')}",
                                image_url=content.get("image_url"),
                                hashtags=content.get("hashtags", []),
                            )
                            mode = "real_published"
                        except FeatureDisabledError:
                            adapter_attempt = {"ok": False, "reason": "feature_disabled"}
                        except AdapterCredentialError as exc:
                            adapter_attempt = {"ok": False, "reason": "credential", "error": str(exc)}
                except Exception as exc:
                    print(f"[NODE publisher] adapter attempt failed: {exc}")
        except Exception as exc:
            print(f"[NODE publisher] credential lookup failed: {exc}")

    # Tool'a delege et — gerçek runtime'da fake tool zaten emit ediyor
    try:
        from tool_registry import resolve_tool_instances
        tool_name = {
            "instagram": "instagram_campaign_tool",
            "banner":    "banner_generator_tool",
            "coupon":    "coupon_generator_tool",
            "faq":       "faq_update_tool",
            "support":   "support_response_tool",
        }.get(channel, "instagram_campaign_tool")
        tools = resolve_tool_instances([tool_name])
        if tools:
            t = tools[0]
            # task_id ataması — execution_id'yi kullan
            t._task_id = state.get("execution_id")
            kwargs = {"headline": content.get("headline", "")}
            if tool_name == "instagram_campaign_tool":
                kwargs["hook"] = content.get("body")
                kwargs["hashtags"] = content.get("hashtags", [])
            elif tool_name == "banner_generator_tool":
                kwargs["subline"] = content.get("body")
                kwargs["cta"] = "Hemen incele"
            elif tool_name == "coupon_generator_tool":
                kwargs = {"label": content.get("headline", "İndirim")}
            elif tool_name == "faq_update_tool":
                kwargs = {
                    "topic": "genel",
                    "question": content.get("headline", "Soru"),
                    "answer": content.get("body", "Cevap"),
                }
            elif tool_name == "support_response_tool":
                kwargs = {"customer_question": content.get("body", "")}
            tool_out = t._run(**kwargs)
        else:
            tool_out = {"success": True, "message": "tool not found (no-op)"}
    except Exception as exc:
        tool_out = {"success": False, "error": str(exc)}

    success = bool(tool_out.get("success"))
    message = tool_out.get("message", "")[:240]
    timeline_id = None  # fake_tool_timeline emit ediyor; id'yi tracking yok

    result = PublishResult(
        channel=channel,
        mode=mode,
        account_handle=handle,
        credential_id=cred_id,
        timeline_event_id=timeline_id,
        success=success,
        message=message,
    )

    summary = (
        f"Yayın {'gerçekleştirildi (mock)' if mode == 'real_publish_would_happen' else 'taslak'}: "
        f"{channel} kanalı."
    )
    _emit("PUBLISH_DONE", {
        "execution_id": state.get("execution_id"),
        "channel": channel, "mode": mode, "success": success,
        "summary": summary,
    }, user_id=user_id)

    return {
        "current_node": "publisher",
        "publish": result.model_dump(),
        "trace_events": [make_trace(
            "publisher", "ok" if success else "failed", summary,
            details={"channel": channel, "mode": mode, "handle": handle},
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: monitor
# ---------------------------------------------------------------------------


def monitor_node(state: RuleExecutionState) -> dict:
    """Yayın sonrası izleme kurulumunu yap (toy: 6 saat sonra check ekle)."""
    t0 = time.monotonic()
    publish = state.get("publish") or {}
    if not publish.get("success"):
        # Yayın olmamış, izleme anlamsız
        return {
            "current_node": "monitor",
            "monitor": MonitorResult(note="Yayın başarısız — izleme kurulmadı.").model_dump(),
            "trace_events": [make_trace(
                "monitor", "ok", "İzleme atlandı (yayın başarısız).",
                duration_ms=int((time.monotonic() - t0) * 1000),
            )],
        }

    when = (datetime.utcnow() + timedelta(hours=6)).isoformat()
    try:
        from scheduling_service import create_schedule
        create_schedule(
            user_id=state.get("user_id") or 1,
            kind="workflow",
            scheduled_at=when,
            title=f"Yayın performans izleme #{state.get('execution_id')}",
            description="Yayının ilk 6 saatlik performansı kontrol edilecek.",
            workflow_name=f"monitor_rule_exec_{state.get('execution_id')}",
            payload={
                "execution_id": state.get("execution_id"),
                "kind": "monitor_check",
            },
        )
    except Exception as exc:
        print(f"[NODE monitor] schedule create failed: {exc}")

    monitor = MonitorResult(
        scheduled_check_at=when,
        initial_metrics={"impressions": 0, "clicks": 0},
        note=f"6 saat sonra ({when}) performans okuma planlandı.",
    )
    summary = monitor.note
    _emit("MONITOR_SCHEDULED", {
        "execution_id": state.get("execution_id"),
        "check_at": when,
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "monitor",
        "monitor": monitor.model_dump(),
        "trace_events": [make_trace(
            "monitor", "ok", summary,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: notify_customer  (opsiyonel — risky/shipping akışlarında kullanılır)
# ---------------------------------------------------------------------------


def notify_customer_node(state: RuleExecutionState) -> dict:
    t0 = time.monotonic()
    event = state.get("event") or {}
    content = state.get("content") or {}

    try:
        from tool_registry import resolve_tool_instances
        tools = resolve_tool_instances(["support_response_tool"])
        if tools:
            t = tools[0]
            t._task_id = state.get("execution_id")
            t._run(
                customer_question=event.get("payload", {}).get("question") or
                                  content.get("body", "Müşteri konusu"),
                tone="friendly",
            )
    except Exception as exc:
        print(f"[NODE notify_customer] tool failed: {exc}")

    return {
        "current_node": "notify_customer",
        "trace_events": [make_trace(
            "notify_customer", "ok", "Müşteriye bilgilendirme gönderildi (taslak).",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: create_coupon  (kupon-yan-eylem)
# ---------------------------------------------------------------------------


def create_coupon_node(state: RuleExecutionState) -> dict:
    t0 = time.monotonic()
    content = state.get("content") or {}
    label = content.get("headline") or "İndirim"
    percent = (_action_config(state, "create_coupon") or {}).get("percent", 10)

    try:
        from tool_registry import resolve_tool_instances
        tools = resolve_tool_instances(["coupon_generator_tool"])
        if tools:
            t = tools[0]
            t._task_id = state.get("execution_id")
            t._run(label=label, percent=int(percent))
    except Exception as exc:
        print(f"[NODE create_coupon] tool failed: {exc}")

    return {
        "current_node": "create_coupon",
        "trace_events": [make_trace(
            "create_coupon", "ok", f"Kupon oluşturuldu (%{percent}, {label}).",
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }


# ---------------------------------------------------------------------------
# Node: finalize — graph sonu
# ---------------------------------------------------------------------------


def finalize_node(state: RuleExecutionState) -> dict:
    t0 = time.monotonic()
    publish = state.get("publish") or {}
    approval = state.get("approval") or {}

    if approval.get("decision") == "rejected":
        status = "cancelled"
        summary = "Kural insan tarafından reddedildi."
    elif publish and not publish.get("success", True):
        status = "failed"
        summary = "Yayın başarısız oldu — akış kapatıldı."
    else:
        status = "completed"
        summary = "Kural başarıyla tamamlandı."

    _emit("RULE_EXECUTION_END", {
        "execution_id": state.get("execution_id"),
        "rule_id": state.get("rule_id"),
        "final_status": status,
        "summary": summary,
    }, user_id=state.get("user_id"))

    return {
        "current_node": "finalize",
        "status": status,
        "trace_events": [make_trace(
            "finalize", "ok", summary,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )],
    }
