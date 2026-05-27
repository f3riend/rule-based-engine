"""
Türkçe doğal dil → StructuredRule parser.

Akış:
    1) Deterministic prefilter — yaygın kalıpları (zaman ifadeleri, kanal,
       şablon, event tetik) regex/keyword ile yakala. Bu, LLM olmadan da
       çoğu örnek için yeterli temel doldurur.
    2) LLM ince ayar — OpenAI gpt-4o-mini'ye prefilter'ın bulgularını ve
       ham metni vererek Pydantic schema'sına uygun JSON üretmesini iste.
    3) Validation — sonucu StructuredRule(**...) ile validate et. Hata
       varsa parse_confidence düşürülür ve missing_fields doldurulur.

Bu hibrit yaklaşım önemli çünkü:
    - LLM down/keysiz çalışırken bile çoğu kural makul şekilde parse edilir.
    - LLM ile daha akıcı dil yapıları (örn. "Çanakkale'deki yeni mağazalar
      için") yakalanır.
    - Her zaman Pydantic ile son doğrulama vardır — runtime'a şüpheli
      yapılar ulaşmaz.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

from structured_rule import (
    ACTION_KINDS,
    CHANNELS,
    CONTENT_TEMPLATES,
    TRIGGER_EVENT_TYPES,
    ActionStep,
    ContentSpec,
    StructuredRule,
    TargetSpec,
    TimingSpec,
    TriggerSpec,
    empty_rule_template,
    utcnow_iso,
)


# ---------------------------------------------------------------------------
# Deterministic prefilter
# ---------------------------------------------------------------------------


# Türkçe event → canonical event_type mapping.
_EVENT_PATTERNS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\byeni\s+ma[ğg]aza\b|\bma[ğg]aza\s+olu[şs]\w*\b|\bma[ğg]aza\s+a[çc][ıi]l\w*\b", re.IGNORECASE), "store.created"),
    (re.compile(r"\bma[ğg]aza\s+g[üu]nce\w*\b", re.IGNORECASE), "store.updated"),
    (re.compile(r"\bma[ğg]aza\s+sil\w*\b|\bma[ğg]aza\s+kapan\w*\b", re.IGNORECASE), "store.deleted"),
    (re.compile(r"\byeni\s+[üu]r[üu]n\b|\b[üu]r[üu]n\s+eklen\w*\b|\b[üu]r[üu]n\s+olu[şs]\w*\b", re.IGNORECASE), "product.created"),
    (re.compile(r"\b[üu]r[üu]n\s+g[üu]nce\w*\b", re.IGNORECASE), "product.updated"),
    (re.compile(r"\byeni\s+sipari[şs]\b|\bsipari[şs]\s+olu[şs]\w*\b", re.IGNORECASE), "order.created"),
    (re.compile(r"\bkargo\w*\s+(?:gecik\w*|geç\w*)\b", re.IGNORECASE), "shipping.delayed"),
    (re.compile(r"\bstok\w*\s+(?:de[ğg]i[şs]\w*|g[üu]ncel\w*)\b", re.IGNORECASE), "stock.updated"),
    (re.compile(r"\bolumsuz\s+yorum\w*\b|\bnegatif\s+yorum\w*\b|\bk[öo]t[üu]\s+yorum\w*\b", re.IGNORECASE), "review.negative"),
    (re.compile(r"\byorum\s+gel\w*\b|\byeni\s+yorum\b", re.IGNORECASE), "review.created"),
    (re.compile(r"\bm[üu][şs]teri\s+sor\w*\b|\bsoru\s+gel\w*\b", re.IGNORECASE), "customer.question"),
    (re.compile(r"\byeni\s+kampanya\b|\bkampanya\s+ba[şs]la\w*\b", re.IGNORECASE), "campaign.created"),
    (re.compile(r"\bbanner\w*\s+(?:g[üu]ncel\w*|de[ğg]i[şs]\w*)\b", re.IGNORECASE), "banner.updated"),
    (re.compile(r"\bsat[ıi][şs]\w*\s+de[ğg]i[şs]\w*\b", re.IGNORECASE), "sales.updated"),
)


# Türkçe zaman ifadeleri → saniye.
_TIME_PATTERNS: tuple[tuple[re.Pattern, int], ...] = (
    (re.compile(r"(\d+)\s*(?:dakika|dk)\s*sonra", re.IGNORECASE), 60),
    (re.compile(r"(\d+)\s*saat\s*sonra", re.IGNORECASE), 3600),
    (re.compile(r"(\d+)\s*g[üu]n\s*sonra", re.IGNORECASE), 86400),
    (re.compile(r"(\d+)\s*hafta\s*sonra", re.IGNORECASE), 604800),
    (re.compile(r"(\d+)\s*ay\s*sonra", re.IGNORECASE), 2592000),
)

# "Anında", "hemen", "şimdi" → 0 saniye.
_IMMEDIATE_RE = re.compile(r"\b(?:hemen|an[ıi]nda|[şs]imdi|derhal)\b", re.IGNORECASE)


# Kanal anahtar kelimeleri.
_CHANNEL_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("instagram", "instagram"),
    ("facebook",  "facebook"),
    ("banner",    "banner"),
    ("kupon",     "coupon"),
    ("coupon",    "coupon"),
    ("e-posta",   "email"),
    ("eposta",    "email"),
    ("email",     "email"),
    ("sms",       "sms"),
    ("trendyol",  "trendyol"),
    ("shopify",   "shopify"),
    ("sss",       "faq"),
    ("faq",       "faq"),
    ("destek",    "support"),
)


# Şablon anahtar kelimeleri — pre-defined holiday/season templates.
_TEMPLATE_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("anneler g",      "anneler_gunu"),
    ("babalar g",      "babalar_gunu"),
    ("y[ıi]lba[şs][ıi]", "yilbasi"),
    ("ramazan",        "ramazan"),
    ("kurban",         "kurban_bayrami"),
    ("yaz indirim",    "yaz_indirim"),
    ("k[ıi][şs] indirim", "kis_indirim"),
    ("kara cuma",      "kara_cuma"),
    ("black friday",   "kara_cuma"),
    ("yeni [üu]r[üu]n lansman", "yeni_urun_lansman"),
    ("magaza a[çc][ıi]l", "magaza_acilis"),
    ("ma[ğg]aza a[çc][ıi]l", "magaza_acilis"),
    ("te[şs]ekk[üu]r",  "tesekkur"),
    ("[öo]z[üu]r",      "ozur"),
    ("[öo]zel indirim", "ozel_indirim"),
)


# "Yapılacak" eylem ifadeleri.
_ACTION_VERBS: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\bpayla[şs][ıi]m\s+yap\w*\b|\bpayla[şs]\w+\b|\b(?:gönder|paylas)\w*\b", re.IGNORECASE), "publish"),
    (re.compile(r"\bkupon\s+olu[şs]\w*\b|\bkupon\s+ver\w*\b", re.IGNORECASE), "create_coupon"),
    (re.compile(r"\bm[üu][şs]teriye\s+bildir\w*\b|\bbilgilendir\w*\b|\bhaber\s+ver\w*\b", re.IGNORECASE), "notify_customer"),
    (re.compile(r"\btakip\s+et\w*\b|\bizle\w*\b|\bg[öo]zlemle\w*\b|\bperformans\s+izle\w*\b", re.IGNORECASE), "monitor"),
    (re.compile(r"\briski\s+kontrol\b|\briski\s+de[ğg]erlendir\w*\b", re.IGNORECASE), "risk_check"),
    (re.compile(r"\bonay\w*\s+al\w*\b|\bonayla\w*\b", re.IGNORECASE), "approval"),
    (re.compile(r"\b(?:i[çc]erik|metin|caption|banner)\s+olu[şs]\w*\b|\b(?:i[çc]erik|metin)\s+[üu]ret\w*\b", re.IGNORECASE), "generate_content"),
)


# Account / şehir handle ipucu — "Çanakkale hesabında" gibi.
_HANDLE_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?P<handle>[A-Za-zÇĞİÖŞÜçğıöşü0-9_]+)\s+hesab[ıi]n[dt]a", re.IGNORECASE),
    re.compile(r"@(?P<handle>[A-Za-z0-9_\.]+)", re.IGNORECASE),
)


@dataclass
class _PrefilterResult:
    event_type: str | None = None
    delay_seconds: int = 0
    immediate: bool = False
    channel: str | None = None
    template: str | None = None
    account_handle: str | None = None
    detected_actions: list[str] = None

    def __post_init__(self):
        if self.detected_actions is None:
            self.detected_actions = []


def _prefilter(text: str) -> _PrefilterResult:
    """Regex tabanlı kaba parser. LLM'siz çalışırken bile temel doldurma."""
    result = _PrefilterResult()
    if not text:
        return result

    # Event tipi
    for pattern, event_type in _EVENT_PATTERNS:
        if pattern.search(text):
            result.event_type = event_type
            break

    # Zaman ifadeleri
    if _IMMEDIATE_RE.search(text):
        result.immediate = True
        result.delay_seconds = 0
    else:
        for pattern, multiplier in _TIME_PATTERNS:
            m = pattern.search(text)
            if m:
                try:
                    result.delay_seconds = int(m.group(1)) * multiplier
                    break
                except (ValueError, IndexError):
                    continue

    # Kanal
    lower = text.lower()
    for keyword, canonical in _CHANNEL_KEYWORDS:
        if keyword in lower:
            result.channel = canonical
            break

    # Şablon
    for keyword_re, template in _TEMPLATE_KEYWORDS:
        if re.search(keyword_re, lower):
            result.template = template
            break

    # Hesap handle
    for pattern in _HANDLE_PATTERNS:
        m = pattern.search(text)
        if m:
            result.account_handle = m.group("handle").strip().lower()
            break

    # Eylem fiilleri
    for pattern, action_kind in _ACTION_VERBS:
        if pattern.search(text):
            if action_kind not in result.detected_actions:
                result.detected_actions.append(action_kind)

    return result


def _default_action_chain(prefilter: _PrefilterResult) -> list[ActionStep]:
    """Prefilter sinyallerinden makul bir eylem zinciri kur.

    Default güvenli akış: bekle → içerik üret → risk kontrol → onay → yayınla → izle
    """
    chain: list[ActionStep] = []

    if prefilter.delay_seconds > 0:
        chain.append(ActionStep(
            kind="wait",
            config={"delay_seconds": prefilter.delay_seconds},
        ))

    if "generate_content" in prefilter.detected_actions or prefilter.template:
        chain.append(ActionStep(
            kind="generate_content",
            config={
                "template": prefilter.template or "generic",
                "channel": prefilter.channel or "instagram",
            },
        ))

    if "create_coupon" in prefilter.detected_actions:
        chain.append(ActionStep(kind="create_coupon"))

    chain.append(ActionStep(kind="risk_check"))

    # Dış yayın varsa onay zorunlu.
    needs_approval = (
        "publish" in prefilter.detected_actions
        or "approval" in prefilter.detected_actions
        or (prefilter.channel in ("instagram", "facebook"))
    )
    if needs_approval:
        chain.append(ActionStep(kind="approval"))

    if "publish" in prefilter.detected_actions or prefilter.template:
        chain.append(ActionStep(kind="publish", config={"channel": prefilter.channel or "instagram"}))

    if "notify_customer" in prefilter.detected_actions:
        chain.append(ActionStep(kind="notify_customer"))

    if "monitor" in prefilter.detected_actions or "publish" in prefilter.detected_actions:
        chain.append(ActionStep(kind="monitor"))

    # En az bir eylem garanti
    if not chain:
        chain.append(ActionStep(kind="generate_content"))

    return chain


# ---------------------------------------------------------------------------
# LLM ince ayar
# ---------------------------------------------------------------------------


_LLM_SYSTEM_PROMPT = """Sen bir Türkçe iş kuralı parser'ısın. Operatörün
yazdığı doğal dil niyetini, JSON yapısına çevireceksin.

Çıktın SADECE geçerli JSON olmalı, başka metin yok. Aşağıdaki şemaya uy:

{
  "name": "Kural için 2-6 kelimelik Türkçe başlık",
  "trigger": {
    "event_type": "store.created | store.updated | store.deleted | product.created | product.updated | order.created | shipping.delayed | stock.updated | review.created | review.negative | customer.question | campaign.created | banner.updated | sales.updated",
    "filters": {}
  },
  "timing": {
    "delay_seconds": 0,
    "recurrence": "once | daily | weekly | monthly"
  },
  "target": {
    "account_handle": null,
    "entity_filters": {}
  },
  "content": {
    "template": "anneler_gunu | babalar_gunu | yilbasi | ramazan | kurban_bayrami | yaz_indirim | kis_indirim | kara_cuma | yeni_urun_lansman | magaza_acilis | tesekkur | ozur | ozel_indirim | generic",
    "channel": "instagram | facebook | banner | coupon | faq | support | email | sms | trendyol | shopify",
    "headline_hint": null
  },
  "actions": [
    {"kind": "wait | generate_content | risk_check | approval | publish | monitor | notify_customer | create_coupon | schedule_followup", "config": {}}
  ],
  "requires_approval": true,
  "missing_fields": []
}

Kurallar:
- trigger.event_type'ı doğru seç. Operatör "yeni mağaza" derse store.created.
- "X gün sonra" → timing.delay_seconds = X * 86400.
- Hesap handle "Çanakkale" gibi belirtilmişse target.account_handle = "canakkale" (küçük harf).
- Şablon adı geçiyorsa content.template'i doğru seç.
- Kanal geçiyorsa content.channel'ı seç.
- actions sırası: wait varsa önce, sonra generate_content, risk_check, approval, publish, monitor.
- Eğer dış yayın (instagram/facebook) varsa requires_approval=true.
- Anlayamadığın alanları missing_fields listesine ekle.
- Cevabın SADECE JSON, başka açıklama yok."""


def _llm_parse(text: str, prefilter: _PrefilterResult) -> dict[str, Any] | None:
    """LLM çağrısı — None döndürürse caller deterministic fallback'e gider."""
    if os.environ.get("NL_PARSER_USE_LLM", "1") == "0":
        return None
    if not os.environ.get("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI

        client = OpenAI(timeout=float(os.environ.get("NL_PARSER_TIMEOUT", "15")))
        hint = {
            "event_type_guess": prefilter.event_type,
            "delay_seconds_guess": prefilter.delay_seconds,
            "channel_guess": prefilter.channel,
            "template_guess": prefilter.template,
            "account_handle_guess": prefilter.account_handle,
            "detected_actions": prefilter.detected_actions,
        }
        completion = client.chat.completions.create(
            model=os.environ.get("NL_PARSER_MODEL", "gpt-4o-mini"),
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"OPERATÖR METNİ:\n{text}\n\n"
                        f"DETERMINISTIC ÖN BULGULAR:\n{json.dumps(hint, ensure_ascii=False)}\n\n"
                        "Şimdi yukarıdaki şemaya uygun JSON üret."
                    ),
                },
            ],
            temperature=0.2,
            max_tokens=600,
        )
        raw = (completion.choices[0].message.content or "").strip()
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        print(f"[NL_PARSER] LLM call failed, falling back: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_rule(
    natural_language: str,
    *,
    user_id: int = 1,
    org_id: int | None = None,
    name_hint: str | None = None,
) -> StructuredRule:
    """Doğal Türkçe niyetten StructuredRule üret.

    Asla hata fırlatmaz; başarısız parse durumunda parse_confidence=0.0
    ve missing_fields dolu bir iskelet döndürür — operatör UI bunu
    "yarım kalmış, lütfen daha açık yaz" mesajıyla gösterebilir.
    """
    text = (natural_language or "").strip()
    if not text:
        return empty_rule_template("")

    prefilter = _prefilter(text)
    llm_json = _llm_parse(text, prefilter)

    # Prefilter'dan iskelet kur
    skeleton: dict[str, Any] = {
        "user_id": user_id,
        "org_id": org_id,
        "name": name_hint or _auto_name(text, prefilter),
        "natural_language": text,
        "trigger": {
            "event_type": prefilter.event_type or "store.created",
            "filters": {},
        },
        "timing": {"delay_seconds": prefilter.delay_seconds, "recurrence": "once"},
        "target": {
            "account_handle": prefilter.account_handle,
            "entity_filters": {},
        },
        "content": {
            "template": prefilter.template or "generic",
            "channel": prefilter.channel or "instagram",
        },
        "actions": [a.model_dump() for a in _default_action_chain(prefilter)],
        "requires_approval": True,
        "missing_fields": [],
        "parse_confidence": 0.55,
        "created_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }

    # LLM çıktısını over-merge — sadece geçerli alanları al
    if llm_json:
        skeleton = _merge_llm_into_skeleton(skeleton, llm_json)
        skeleton["parse_confidence"] = 0.9

    # Eksik alanları tespit et
    missing: list[str] = []
    if not prefilter.event_type and not llm_json:
        missing.append("trigger.event_type")
    if not prefilter.template and skeleton["content"]["template"] == "generic":
        missing.append("content.template")
    if not prefilter.account_handle and not (llm_json and (llm_json.get("target") or {}).get("account_handle")):
        # Optional — only flag if rule explicitly mentions a city/handle hint
        pass
    skeleton["missing_fields"] = missing
    if missing and skeleton["parse_confidence"] > 0.7:
        skeleton["parse_confidence"] = 0.7

    try:
        return StructuredRule(**skeleton)
    except Exception as exc:
        print(f"[NL_PARSER] validation failed: {exc}")
        fallback = empty_rule_template(text)
        fallback.missing_fields = [f"validation_error: {exc}"]
        return fallback


def _merge_llm_into_skeleton(skeleton: dict, llm: dict) -> dict:
    """LLM JSON'dan güvenli üyeleri skeleton'a kopyala."""
    out = dict(skeleton)

    if isinstance(llm.get("name"), str) and llm["name"].strip():
        out["name"] = llm["name"].strip()[:120]

    if isinstance(llm.get("trigger"), dict):
        et = llm["trigger"].get("event_type")
        if isinstance(et, str) and et.strip().lower() in TRIGGER_EVENT_TYPES:
            out["trigger"]["event_type"] = et.strip().lower()
        if isinstance(llm["trigger"].get("filters"), dict):
            out["trigger"]["filters"] = llm["trigger"]["filters"]

    if isinstance(llm.get("timing"), dict):
        delay = llm["timing"].get("delay_seconds")
        if isinstance(delay, (int, float)) and delay >= 0:
            out["timing"]["delay_seconds"] = int(delay)
        rec = llm["timing"].get("recurrence")
        if rec in ("once", "daily", "weekly", "monthly"):
            out["timing"]["recurrence"] = rec

    if isinstance(llm.get("target"), dict):
        h = llm["target"].get("account_handle")
        if isinstance(h, str) and h.strip():
            out["target"]["account_handle"] = h.strip().lower()
        if isinstance(llm["target"].get("entity_filters"), dict):
            out["target"]["entity_filters"] = llm["target"]["entity_filters"]

    if isinstance(llm.get("content"), dict):
        t = llm["content"].get("template")
        if isinstance(t, str) and t.strip().lower() in CONTENT_TEMPLATES:
            out["content"]["template"] = t.strip().lower()
        ch = llm["content"].get("channel")
        if isinstance(ch, str) and ch.strip().lower() in CHANNELS:
            out["content"]["channel"] = ch.strip().lower()
        hint = llm["content"].get("headline_hint")
        if isinstance(hint, str) and hint.strip():
            out["content"]["headline_hint"] = hint.strip()[:200]

    if isinstance(llm.get("actions"), list) and llm["actions"]:
        valid_actions: list[dict] = []
        for a in llm["actions"]:
            if not isinstance(a, dict):
                continue
            kind = (a.get("kind") or "").strip().lower()
            if kind in ACTION_KINDS:
                valid_actions.append({
                    "kind": kind,
                    "config": a.get("config") if isinstance(a.get("config"), dict) else {},
                })
        if valid_actions:
            out["actions"] = valid_actions

    if isinstance(llm.get("requires_approval"), bool):
        out["requires_approval"] = llm["requires_approval"]

    if isinstance(llm.get("missing_fields"), list):
        out["missing_fields"] = [str(x) for x in llm["missing_fields"]][:8]

    return out


def _auto_name(text: str, prefilter: _PrefilterResult) -> str:
    """Operatöre okunaklı bir kural adı türet."""
    if prefilter.template and prefilter.event_type:
        tmpl = prefilter.template.replace("_", " ").title()
        return f"{tmpl} • {prefilter.event_type}"[:80]
    if prefilter.event_type:
        return f"Kural: {prefilter.event_type}"
    # İlk birkaç kelime
    words = text.split()[:6]
    return " ".join(words)[:80] or "Yeni Kural"


def explain_rule(rule: StructuredRule) -> str:
    """Operatöre kuralın insan diliyle ne yapacağını anlatan kısa özet.

    UI bunu "önizleme" alanında gösterir, böylece operatör yazdığı şeyin
    nasıl yorumlandığını görür.
    """
    parts: list[str] = []

    parts.append(f"**Tetik:** {_event_label(rule.trigger.event_type)}.")

    if rule.timing.delay_seconds > 0:
        parts.append(f"**Bekleme:** {_humanize_seconds(rule.timing.delay_seconds)} sonra.")
    if rule.timing.recurrence != "once":
        parts.append(f"**Tekrar:** {_recurrence_label(rule.timing.recurrence)}.")

    if rule.target.account_handle:
        parts.append(f"**Hesap:** @{rule.target.account_handle}.")

    if rule.content.template != "generic":
        parts.append(f"**İçerik şablonu:** {_template_label(rule.content.template)}.")
    parts.append(f"**Kanal:** {_channel_label(rule.content.channel)}.")

    if rule.actions:
        action_labels = [_action_label(a.kind) for a in rule.actions]
        parts.append("**Akış:** " + " → ".join(action_labels) + ".")

    if rule.requires_approval:
        parts.append("**Onay:** Yayın öncesi insan onayı bekleyecek.")

    if rule.missing_fields:
        parts.append(
            "**Eksik bilgiler:** " + ", ".join(rule.missing_fields) +
            ". Lütfen kuralı netleştirin."
        )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Türkçe etiket yardımcıları (UI tarafına)
# ---------------------------------------------------------------------------


def _event_label(event_type: str) -> str:
    return ({
        "store.created":      "Yeni mağaza oluşturulduğunda",
        "store.updated":      "Mağaza güncellendiğinde",
        "store.deleted":      "Mağaza silindiğinde",
        "product.created":    "Yeni ürün eklendiğinde",
        "product.updated":    "Ürün güncellendiğinde",
        "order.created":      "Yeni sipariş geldiğinde",
        "order.shipped":      "Sipariş kargoya verildiğinde",
        "order.cancelled":    "Sipariş iptal edildiğinde",
        "shipping.delayed":   "Kargo gecikmesi olduğunda",
        "stock.updated":      "Stok değiştiğinde",
        "review.created":     "Yeni müşteri yorumu geldiğinde",
        "review.negative":    "Olumsuz yorum geldiğinde",
        "customer.question":  "Müşteri sorusu olduğunda",
        "campaign.created":   "Yeni kampanya başladığında",
        "banner.updated":     "Banner güncellendiğinde",
        "sales.updated":      "Satış verileri güncellendiğinde",
    }.get(event_type, event_type))


def _template_label(template: str) -> str:
    return ({
        "anneler_gunu":       "Anneler Günü",
        "babalar_gunu":       "Babalar Günü",
        "yilbasi":            "Yılbaşı",
        "ramazan":            "Ramazan",
        "kurban_bayrami":     "Kurban Bayramı",
        "yaz_indirim":        "Yaz İndirimi",
        "kis_indirim":        "Kış İndirimi",
        "kara_cuma":          "Kara Cuma",
        "yeni_urun_lansman":  "Yeni Ürün Lansmanı",
        "magaza_acilis":      "Mağaza Açılışı",
        "tesekkur":           "Teşekkür",
        "ozur":               "Özür",
        "ozel_indirim":       "Özel İndirim",
        "generic":            "Genel İçerik",
    }.get(template, template))


def _channel_label(channel: str) -> str:
    return ({
        "instagram":  "Instagram",
        "facebook":   "Facebook",
        "banner":     "Banner",
        "coupon":     "Kupon",
        "faq":        "SSS",
        "support":    "Destek",
        "email":      "E-posta",
        "sms":        "SMS",
        "trendyol":   "Trendyol",
        "shopify":    "Shopify",
    }.get(channel, channel))


def _action_label(kind: str) -> str:
    return ({
        "wait":             "Bekle",
        "generate_content": "İçerik üret",
        "risk_check":       "Risk kontrolü",
        "approval":         "Onay",
        "publish":          "Yayınla",
        "monitor":          "İzle",
        "notify_customer":  "Müşteriye bildir",
        "create_coupon":    "Kupon üret",
        "schedule_followup": "Takip planla",
    }.get(kind, kind))


def _recurrence_label(rec: str) -> str:
    return ({
        "once":     "Bir kez",
        "daily":    "Her gün",
        "weekly":   "Haftalık",
        "monthly":  "Aylık",
    }.get(rec, rec))


def _humanize_seconds(s: int) -> str:
    if s <= 0:
        return "hemen"
    if s < 3600:
        m = max(1, s // 60)
        return f"{m} dakika"
    if s < 86400:
        h = max(1, s // 3600)
        return f"{h} saat"
    if s < 604800:
        d = max(1, s // 86400)
        return f"{d} gün"
    if s < 2592000:
        w = max(1, s // 604800)
        return f"{w} hafta"
    mo = max(1, s // 2592000)
    return f"{mo} ay"
