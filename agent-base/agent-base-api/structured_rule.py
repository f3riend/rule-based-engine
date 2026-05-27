"""
Structured Rule schema — operatörün doğal dil niyetinin canonical formu.

Operatör Türkçe yazar:
    "Yeni mağaza oluştuktan 3 gün sonra Çanakkale hesabında Anneler Günü
     şablonu kullanarak Instagram paylaşımı yap."

nl_rule_parser bunu bir StructuredRule'a dönüştürür. structured_rule_engine
gelen olayları enabled=true rules ile eşler. langgraph.runtime bu rule'u
runtime'da bir StateGraph'a derler.

Tüm alanlar Pydantic ile validated — runtime'a ulaşmadan önce yapısal
hatalar (bilinmeyen event_type, geçersiz channel, vb.) yakalanır.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Canonical taxonomy — uzantı için tek nokta
# ---------------------------------------------------------------------------


# Tetik olabilecek event tipleri (mevcut event_router.CRITICAL/CREATIVE
# prefix tablolarıyla aynı vokabüler). Yeni event eklerken bu listeyi
# güncelle.
TRIGGER_EVENT_TYPES: tuple[str, ...] = (
    "store.created",
    "store.updated",
    "store.rejected",
    "store.deleted",
    "product.created",
    "product.updated",
    "product.deleted",
    "order.created",
    "order.shipped",
    "order.cancelled",
    "stock.updated",
    "shipping.delayed",
    "review.created",
    "review.negative",
    "customer.question",
    "campaign.created",
    "banner.updated",
    "sales.updated",
)

CHANNELS: tuple[str, ...] = (
    "instagram",
    "facebook",
    "banner",
    "coupon",
    "faq",
    "support",
    "email",
    "sms",
    "trendyol",
    "shopify",
)

# Operatörün konuşma dilinde kullanabileceği şablon isimleri.
# Yeni şablon ekleme: bu listeyi genişlet + nl_rule_parser'a yansı.
CONTENT_TEMPLATES: tuple[str, ...] = (
    "anneler_gunu",
    "babalar_gunu",
    "yilbasi",
    "ramazan",
    "kurban_bayrami",
    "yaz_indirim",
    "kis_indirim",
    "kara_cuma",
    "yeni_urun_lansman",
    "magaza_acilis",
    "tesekkur",
    "ozur",
    "ozel_indirim",
    "generic",
)

# Eylem türleri — graph'taki node'lara birebir karşılık gelir.
ACTION_KINDS: tuple[str, ...] = (
    "wait",
    "generate_content",
    "risk_check",
    "approval",
    "publish",
    "monitor",
    "notify_customer",
    "create_coupon",
    "schedule_followup",
)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class TriggerSpec(BaseModel):
    """Hangi olay bu kuralı tetikler."""
    model_config = ConfigDict(extra="forbid")

    event_type: str = Field(
        description="Tam canonical event adı (örn. 'store.created')."
    )
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Olay payload'unda eşleşmesi gereken alanlar.",
    )

    @field_validator("event_type")
    @classmethod
    def _validate_event_type(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in TRIGGER_EVENT_TYPES:
            raise ValueError(
                f"unknown trigger event_type {v!r}; expected one of "
                f"{TRIGGER_EVENT_TYPES}"
            )
        return v


class TimingSpec(BaseModel):
    """Eylem zamanlama: tetik sonrası gecikme veya schedule."""
    model_config = ConfigDict(extra="forbid")

    delay_seconds: int = Field(
        default=0, ge=0, le=60 * 60 * 24 * 365,
        description="Tetik anından eyleme kadar geçecek saniye.",
    )
    schedule_at: str | None = Field(
        default=None,
        description="ISO 8601 mutlak zaman — verilirse delay_seconds göz ardı edilir.",
    )
    recurrence: Literal["once", "daily", "weekly", "monthly"] = "once"


class TargetSpec(BaseModel):
    """Eylemin yöneldiği hesap / varlık filtresi."""
    model_config = ConfigDict(extra="forbid")

    account_handle: str | None = Field(
        default=None,
        description="Sosyal hesap handle'ı (örn. 'canakkale_store').",
    )
    entity_type: str | None = Field(
        default=None,
        description="store | item | order | review — opsiyonel daraltma.",
    )
    entity_filters: dict[str, Any] = Field(
        default_factory=dict,
        description="Tetiklenen entity'de aranan alanlar (örn. {'city': 'Çanakkale'}).",
    )


class ContentSpec(BaseModel):
    """Üretilecek içeriğin şablonu ve kanalı."""
    model_config = ConfigDict(extra="forbid")

    template: str = Field(
        default="generic",
        description="İçerik şablonu (anneler_gunu, yilbasi, vb.).",
    )
    channel: str = Field(
        default="instagram",
        description="Yayın kanalı (instagram, banner, ...).",
    )
    headline_hint: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)

    @field_validator("template")
    @classmethod
    def _validate_template(cls, v: str) -> str:
        v = (v or "generic").strip().lower()
        if v not in CONTENT_TEMPLATES:
            # Bilinmeyen şablon hata değil — parser tahmin etmiş olabilir.
            # generic'e düşür.
            return "generic"
        return v

    @field_validator("channel")
    @classmethod
    def _validate_channel(cls, v: str) -> str:
        v = (v or "instagram").strip().lower()
        if v not in CHANNELS:
            raise ValueError(
                f"unsupported channel {v!r}; expected one of {CHANNELS}"
            )
        return v


class ActionStep(BaseModel):
    """Graph içinde tek bir node'a karşılık gelen eylem."""
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="Eylem türü (action_kinds içinden).")
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ACTION_KINDS:
            raise ValueError(
                f"unknown action kind {v!r}; expected one of {ACTION_KINDS}"
            )
        return v


# ---------------------------------------------------------------------------
# Top-level rule
# ---------------------------------------------------------------------------


class StructuredRule(BaseModel):
    """Operatörün doğal dil niyetinin canonical, deterministic temsili.

    `id` ve `org_id` veritabanı tarafı; parser tarafından doldurulmaz.
    """
    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    user_id: int = 1
    org_id: int | None = None

    name: str = Field(min_length=2, max_length=120)
    natural_language: str = Field(
        description="Operatörün yazdığı ham Türkçe metin."
    )

    trigger: TriggerSpec
    timing: TimingSpec = Field(default_factory=TimingSpec)
    target: TargetSpec = Field(default_factory=TargetSpec)
    content: ContentSpec = Field(default_factory=ContentSpec)
    actions: list[ActionStep] = Field(
        min_length=1,
        description=(
            "Eylem zinciri — graph builder bunları sırayla node'lara dönüştürür."
        ),
    )

    requires_approval: bool = True
    enabled: bool = True

    parse_confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Parser'ın bu yapıya ne kadar emin olduğu.",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Parser'ın belirleyemediği ama belki gereken alanlar.",
    )

    created_at: str | None = None
    updated_at: str | None = None

    # ----- Convenience -----

    def trigger_key(self) -> str:
        """structured_rule_engine.find_matching'in O(1) lookup için kullandığı anahtar."""
        return self.trigger.event_type

    def has_action(self, kind: str) -> bool:
        return any(a.kind == kind for a in self.actions)

    def get_action(self, kind: str) -> ActionStep | None:
        for a in self.actions:
            if a.kind == kind:
                return a
        return None

    def to_storage_dict(self) -> dict[str, Any]:
        """DB'ye yazılacak temiz dict."""
        return self.model_dump(mode="json", exclude_none=False)

    @classmethod
    def from_storage(cls, row: dict[str, Any] | Any) -> "StructuredRule":
        """structured_rules DB satırından restore.

        ÖNEMLİ: rule_json içindeki `id` çoğunlukla None'dır (kayıt
        sırasında üretilmemişti). DB sütunundaki canonical id'yi her
        zaman zorla bind et — setdefault hatası birden fazla turda
        execution id=None'a yol açıyordu.
        """
        import json
        d = dict(row)
        rule_json = d.get("rule_json") or "{}"
        try:
            parsed = json.loads(rule_json)
        except json.JSONDecodeError:
            parsed = {}
        # DB sütunlarını authoritative kabul et — rule_json eski/None
        # değerlere sahip olabilir.
        parsed["id"]               = d.get("id")
        parsed["user_id"]          = d.get("user_id", parsed.get("user_id", 1))
        parsed["org_id"]           = d.get("org_id", parsed.get("org_id"))
        parsed["name"]             = d.get("name", parsed.get("name", "rule"))
        parsed["natural_language"] = d.get("natural_language",
                                           parsed.get("natural_language", ""))
        parsed["created_at"]       = d.get("created_at", parsed.get("created_at"))
        parsed["updated_at"]       = d.get("updated_at", parsed.get("updated_at"))
        if "enabled" in d:
            parsed["enabled"] = bool(d.get("enabled"))
        return cls(**parsed)


# ---------------------------------------------------------------------------
# Public API helpers
# ---------------------------------------------------------------------------


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def empty_rule_template(natural_language: str) -> StructuredRule:
    """Parser başarısız olduğunda fallback olarak dönen iskelet."""
    return StructuredRule(
        name="Parse Edilemedi",
        natural_language=natural_language,
        trigger=TriggerSpec(event_type="store.created"),
        actions=[ActionStep(kind="generate_content")],
        parse_confidence=0.0,
        missing_fields=["trigger.event_type", "actions"],
        enabled=False,
    )
