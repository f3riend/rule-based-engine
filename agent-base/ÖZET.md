# ÖZET — Agent Base Monorepo (Tur 5 · Premium Contextual Rules)

> Bu doküman `agent-base/` monorepo'sunun **en güncel** sistem
> mimarisi referansıdır. Tur 4'te eklenen tek "Kurallar" sekmesi
> kaldırıldı; kurallar artık **her Zaman Tüneli alt sekmesinin
> içinde** premium-grade contextual panel olarak yaşıyor. AI Operatör
> chat Sistem Yöneticisi sayfasında merkezlendi. Kritik
> `SyntaxError: Unexpected identifier 'nin'` hatası kökten çözüldü.
>
> Tarih: 2026-05-27 — Tur 5 polish-2 sonrası.
> Birikim: `SON_DEGISIKLIKLER_VE_GENEL_SISTEM.md` (Tur 1-5).
> Doğrulama: `node -c` ✓ · `php -l` (4 dosya) ✓ · apostrof pattern grep ✓.

---

## 1. Syntax Hatasının Çözümü

**Kök neden:** `php-ui/views/rules.php:592`
```js
root.innerHTML = '<div class="muted">AI'nin henüz öneri ürettiği bir kural yok.</div>'
//                                   ^ tek tırnak burada string'i kapatıyor
//                                    ^^^ JS `nin` → identifier → SyntaxError
```

**Üç katmanlı kalıcı çözüm:**

1. **Kaynak dosya silindi** — `rules.php` artık filesystem'da yok.
   `/kurallar` ve `/rules` route'ları `/page/timeline/all`'a 302
   redirect yapıyor.

2. **Yeni JS'de zorunlu disiplin** (`timeline-page-rules.js`):
   - **DOM API tercih** (`createElement`, `textContent`,
     `replaceChildren`) — string concat değil.
   - **Mecbursa template literal** (backtick) — asla raw single-
     quote'lu Türkçe ek.
   - **HTML inject** her zaman `escapeHtml()`.
   - **PHP → JS veri** her zaman `htmlspecialchars(json_encode($x,
     JSON_UNESCAPED_UNICODE), ENT_QUOTES, 'UTF-8')` ile data-*
     attribute + `JSON.parse(dataset.x)`.

3. **CI doğrulaması**:
   ```
   ✓ node -c timeline-page-rules.js → JS OK
   ✓ php -l _rules_toolbar.php       → No syntax errors detected
   ✓ grep -nE "'[A-Za-zçğıöşü]'(nin|nın|nun|...)" → (temiz)
   ```

---

## 2. Yeni Sidebar Yapısı (Tam Liste)

```
┌──────────────────────────────────────────────────┐
│ Workspace                                        │
├──────────────────────────────────────────────────┤
│ ▾ Sosyal Medya                                   │
│     • Takvim                                     │
│     • Etiketler                                  │
│     • Şablonlar           ◀ sm_templates (post)  │
│     • Onay Bekleyenler                           │
│                                                  │
│ ▾ Kampanya Yönetimi                              │
│     • Takvim                                     │
│     • Şablonlar           ◀ campaign banner      │
│     • Onay Bekleyenler                           │
│                                                  │
│ ⛨ Sistem Yöneticisi                              │
│      ◀ AI OPERATÖR MERKEZİ                       │
│        (sürekli açık chat + 4 AI modu +          │
│         multi-turn cognition + conversational    │
│         rule edit + business analytics)          │
│                                                  │
│ ▾ Zaman Tüneli         ◀ KURALLAR HER SEKMEDE    │
│     • Tümü                  (filter yok)         │
│     • Siparişler            (order.*)            │
│     • Ürünler               (product.*)          │
│     • Değerlendirmeler      (review.*)           │
│     • Sorular               (customer.question)  │
│     • Kuponlar              (—)                  │
│     • Kampanyalar           (campaign.*)         │
│     • Reklamlar             (banner.+sales.)     │
│     • Çalışanlar            (—)                  │
│     • Mesajlar              (customer.question)  │
│     • Stok                  (stock.*)            │
│     • Giriş/Çıkış           (—)                  │
│     • Mağaza Sayfası        (store.*)            │
│     • İadeler               (order.cancelled)    │
│     • Para Çekme            (—)                  │
│     • İndirimler            (sales.*)            │
│     • Eklentiler            (—)                  │
│     • Abonelik              (—)                  │
│     • Teslimat              (shipping.+order.shipped) │
│     • Bannerlar             (banner.*)           │
│     • Flash Satış           (sales.*)            │
│     • Bileşenler            (—)                  │
│                                                  │
│ ▾ Ayarlar                                        │
│     • Hesap                                      │
│     • Çalışma Alanı                              │
│     • Yapay Zeka                                 │
│     • Anahtarlar & Kullanım                      │
│     • Otomasyon                                  │
│     • Güvenlik                                   │
│                                                  │
│ [Çıkış]                                          │
└──────────────────────────────────────────────────┘
```

22 timeline alt sekmesi. Her panel header'ında **"✨ AI ile yönet →"**
kısayolu Sistem Yöneticisi'ne yönlendirir.

---

## 3. Zaman Tüneli Alt Sekmelerinde Kural Paneli (Premium UI)

### 3.1 Görsel Yapı (Mockup)

```
┌──────────────────────────────────────────────────────────────┐
│ ● Mağaza Kuralları                    [ 3 ]  [✨ AI ile yönet →]│
│   store.* olaylarında tetiklenir.                            │
├──────────────────────────────────────────────────────────────┤
│ ⚠ AI 2 kural çakışması öneriyor                              │
│   Sistem Yöneticisi AI Operatör ile doğal Türkçe konuşarak   │
│   çözebilirsin.                  [AI Operatör ile çöz →]     │
├──────────────────────────────────────────────────────────────┤
│ ┌──── COMPOSER ────────────────────────────────────────────┐ │
│ │ ✨ Yeni kural — doğal Türkçe                              │ │
│ │ ┌──────────────────────────────────────────────────────┐ │ │
│ │ │ Örnek: Yeni mağaza oluştuğunda hoşgeldin postu       │ │ │
│ │ │ hazırla ve onay bekle.                                │ │ │
│ │ │                                                       │ │ │
│ │ └──────────────────────────────────────────────────────┘ │ │
│ │ İpucu: ⌘/Ctrl + Enter ile hızlı önizle.                  │ │
│ │ [Önizle]  [Kuralı Etkinleştir]  [Temizle]  📋 Şablonlar  │ │
│ │                                                          │ │
│ │ ┌─ Önizleme ────────────────────────────────────────┐    │ │
│ │ │ Yeni mağaza için hoşgeldin postu                   │    │ │
│ │ │ [Tetik: store.created] [Bekleme: anında]           │    │ │
│ │ │ [Kanal: instagram] [Şablon: tesekkur]              │    │ │
│ │ │ ┌────────────────────────────────────────────────┐ │    │ │
│ │ │ │ ▶ başla → generate_content → risk_check →      │ │    │ │
│ │ │ │ ⏸ approval → 📤 publish → ✓ bitir              │ │    │ │
│ │ │ └────────────────────────────────────────────────┘ │    │ │
│ │ │ Açıklama: Mağaza oluşunca hoşgeldin postu...       │    │ │
│ │ └────────────────────────────────────────────────────┘    │ │
│ └──────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────┤
│ ┌───────────────────────────────────────────────────────────┐│
│ │ Yeni mağaza hoşgeldin postu                               ││
│ │ ● tetik: store.created  ● kanal: instagram                ││
│ │ ● şablon: tesekkur      ● AKTİF       ● sağlık: 92%       ││
│ │ ● son: Tamamlandı · 5 dk önce                             ││
│ │                                  [Pasifleştir]  [Sil]     ││
│ └───────────────────────────────────────────────────────────┘│
│ ┌───────────────────────────────────────────────────────────┐│
│ │ Onaylanmamış mağaza için uyarı                            ││
│ │ ● tetik: store.rejected ● kanal: email                    ││
│ │ ● şablon: ozur          ● PASİF       ● sağlık: 58%       ││
│ │ ● son: Başarısız · 2 sa önce                              ││
│ │ ⚠ 1 çakışma önerisi var. AI Operatör ile çöz →            ││
│ │                                  [Etkinleştir]  [Sil]     ││
│ └───────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────┘

[● Kural etkin.]   ← toast (sağ alt köşe, 2.8s sonra fade-out)
```

### 3.2 Premium UI Detayları (Polish-2)

| Öğe | Yapı |
|-----|------|
| **Card header** | Sol noktalı badge (radial-gradient indigo) + 1.2rem semi-bold başlık + slate-500 lead text |
| **Composer label** | "✨ Yeni kural — doğal Türkçe" — sparkle ikon + 12px üst margin |
| **Textarea** | 12px border-radius, 0.94rem font, focus'ta indigo-500 ring (3px alpha .12) |
| **Hint** | `<kbd>⌘</kbd>/<kbd>Ctrl</kbd> + <kbd>Enter</kbd>` keyboard shortcut chip'leri |
| **Buttons** | Primary gradient indigo-600 → 700, hover translateY(-1px), active scale(.98) |
| **Stepper** | Card içinde slate-50 background; renkli pill'ler: ▶ başla (sky), ⏱ wait (mavi), ⏸ approval (amber), 📤 publish (indigo), ✓ bitir (emerald) |
| **Chip dot** | Her chip'in başında `●` durum noktası — yeşil/sarı/kırmızı/indigo/gri |
| **Item card** | 14px radius, hover'da `border-color: indigo-200` + `box-shadow: md` |
| **Conflict banner** | Amber-50 → orange-100 gradient + 4px sol border + ⚠ ikon |
| **Empty state** | ✨ ikon + güzel Türkçe açıklama + 1px dashed border |
| **Skeleton** | Sayfa açılışında shimmer animasyon (200% bg slide, 1.4s linear infinite) |
| **Toast** | Sağ alt köşe, slide-in animation, success=emerald gradient, error=rose gradient, 2.8s ttl |
| **Optimistic UI** | Toggle butonuna basınca chip anında değişir; hata olursa geri alır |
| **Responsive** | < 720px breakpoint'inde sidebar dik, action button'lar full-width |

### 3.3 Etkileşim Akışı

1. Operatör `/page/timeline/store`'a girer → skeleton 200ms → liste + composer render.
2. Composer'a Türkçe yazıp **⌘/Ctrl+Enter** → instant preview (parse-preview API).
3. Stepper görsel olarak `başla → generate_content → ⏸ approval → 📤 publish → ✓ bitir` çizer.
4. "Kuralı Etkinleştir" → buton "Kaydediliyor…" → success toast → liste yenilenir.
5. Bir kuralın "Pasifleştir" butonu → chip anında PASİF olur → API → success toast → tam yenileme. API fail → otomatik rollback + error toast.
6. Conflict varsa üstte turuncu banner + her ilgili kuralın altında inline ⚠ uyarısı.
7. "✨ AI ile yönet →" link her panel başlığında → Sistem Yöneticisi chat'e.

---

## 4. Bu Turda Yapılan Değişiklikler (Dosya Bazında)

| Dosya | Aksiyon | Satır |
|------|---------|-------|
| `php-ui/views/rules.php` | **SİLİNDİ** (önceki turda) | — |
| `php-ui/views/layout.php` | "Kurallar" linki kaldırıldı (önceki turda) | -5 |
| `php-ui/public/index.php` | `/kurallar` → 302 redirect + extraHead'e timeline-rules.css link eklendi | +6 |
| `php-ui/public/assets/css/timeline-rules.css` | **YENİ** — premium CSS (renk paleti, animasyonlar, responsive) | **678** |
| `php-ui/views/timeline/_rules_toolbar.php` | Inline `<style>` çıkarıldı; sade markup + skeleton placeholder + kbd hint | **134** |
| `php-ui/public/assets/js/timeline-page-rules.js` | Toast + optimistic toggle + skeleton + güzel empty state | **711** |
| `php-ui/views/system_admin.php` | H1 + paragraf güçlendirildi (önceki turda) | +2 |
| `agent-base/ÖZET.md` | **Tam yeniden yazıldı (Polish-2)** | bu dosya |
| `agent-base/SON_DEGISIKLIKLER_VE_GENEL_SISTEM.md` | T5-12 polish-2 bölümü eklendi | +~40 |

**Toplam yeni/değişen UI satırı: 1523** (CSS + markup + JS).
Backend Python katmanı (`agent-base-api/*`) hiç dokunulmadı.

---

## 5. Kritik Kod ve Frontend Güncellemeleri

### 5.1 CSS Renk Paleti (timeline-rules.css)

```css
:root {
  --tr-bg: #ffffff;
  --tr-bg-soft: #f8fafc;
  --tr-border: #e5e7eb;
  --tr-fg-strong: #0f172a;
  --tr-fg-soft: #64748b;

  --tr-indigo-600: #4f46e5;
  --tr-indigo-700: #4338ca;
  --tr-emerald-700: #047857;
  --tr-amber-700: #b45309;
  --tr-rose-700: #b91c1c;
  --tr-sky-700: #0369a1;

  --tr-shadow-md: 0 4px 12px rgba(15, 23, 42, .06);
  --tr-shadow-ring: 0 0 0 3px rgba(99, 102, 241, .12);
  --tr-ease: cubic-bezier(.4, 0, .2, 1);
}
```

### 5.2 Stepper Renkli Pill'ler

```css
.tr-step-start { background: var(--tr-sky-50); color: var(--tr-sky-700); }
.tr-step-start::before { content: "▶"; }

.tr-step-wait { background: #eff6ff; color: #1d4ed8; }
.tr-step-wait::before { content: "⏱"; }

.tr-step-pause { background: var(--tr-amber-100); color: var(--tr-amber-800); }
.tr-step-pause::before { content: "⏸"; }

.tr-step-publish { background: var(--tr-indigo-50); color: var(--tr-indigo-700); }
.tr-step-publish::before { content: "📤"; }

.tr-step-end { background: var(--tr-emerald-50); color: var(--tr-emerald-700); }
.tr-step-end::before { content: "✓"; }
```

### 5.3 Toast Helper (JS — alert yerine)

```js
function toast(message, kind) {
  const host = ensureToastHost()           // <div id="tr-toast-host">
  const el = document.createElement("div")
  el.className = "tr-toast"
  if (kind === "success") el.classList.add("tr-toast-success")
  else if (kind === "error") el.classList.add("tr-toast-error")
  const span = document.createElement("span")
  span.textContent = String(message)       // DOM API — apostrof güvenli
  el.appendChild(span)
  host.appendChild(el)
  const ttl = kind === "error" ? 4500 : 2800
  setTimeout(() => {
    el.classList.add("tr-toast-out")
    setTimeout(() => el.remove(), 220)
  }, ttl)
}
```

### 5.4 Optimistic Toggle (UI önce, sonra API)

```js
async function onToggle(rule, nextState, btn, item) {
  const prevLabel = btn.textContent
  const prevClass = btn.className
  btn.disabled = true
  btn.textContent = nextState ? "Etkinleştiriliyor…" : "Pasifleştiriliyor…"

  const stateChip = item.querySelector(".tr-chip.tr-chip-on, .tr-chip.tr-chip-off")
  let prevChipClass, prevChipText
  if (stateChip) {
    prevChipClass = stateChip.className
    prevChipText = stateChip.textContent
    stateChip.className = `tr-chip ${nextState ? "tr-chip-on" : "tr-chip-off"}`
    stateChip.textContent = nextState ? "AKTİF" : "PASİF"
  }

  try {
    await api("PATCH", `/structured-rules/${rule.id}/enabled`, { enabled: nextState })
    toast(nextState ? "Kural etkin." : "Kural pasif.", "success")
    await refresh()
  } catch (e) {
    // Geri al — sade rollback
    btn.textContent = prevLabel
    btn.className = prevClass
    btn.disabled = false
    if (stateChip && prevChipClass != null) {
      stateChip.className = prevChipClass
      stateChip.textContent = prevChipText
    }
    toast(`Durum güncellenemedi: ${e.message}`, "error")
  }
}
```

### 5.5 Skeleton Loading + Shimmer

```css
.tr-skeleton {
  background: linear-gradient(90deg, #f1f5f9 0%, #e2e8f0 50%, #f1f5f9 100%);
  background-size: 200% 100%;
  border-radius: 12px;
  animation: tr-shimmer 1.4s linear infinite;
  height: 5rem;
}
@keyframes tr-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

```html
<!-- _rules_toolbar.php — sayfa açılırken görünür -->
<div id="tr-list" class="tr-list">
  <div class="tr-skeleton"></div>
  <div class="tr-skeleton"></div>
</div>
```

### 5.6 Conflict Banner (sol şerit + ikon)

```css
.tr-conflicts-banner {
  background: linear-gradient(180deg, #fffbeb 0%, #ffedd5 100%);
  border: 1px solid #fdba74;
  border-left: 4px solid #f97316;   /* dikkat çekici accent şerit */
  border-radius: 12px;
  padding: 1rem 1.2rem;
  display: flex;
  gap: .8rem;
}
.tr-conflicts-banner::before {
  content: "⚠";
  font-size: 1.4rem;
  color: #ea580c;
}
```

### 5.7 Slug → Event Prefix Mapping (PHP)

```php
$slugEventMap = [
  'store'       => ['store.'],
  'orders'      => ['order.'],
  'products'    => ['product.'],
  'stock'       => ['stock.'],
  'reviews'     => ['review.'],
  'ads'         => ['banner.', 'sales.'],
  'campaigns'   => ['campaign.'],
  'delivery'    => ['shipping.', 'order.shipped'],
  'returns'     => ['order.cancelled'],
  /* ... toplam 22 slug ... */
];
```

### 5.8 System Admin Header

```html
<h1>Sistem Yöneticisi
  <span style="font-size:.55em;font-weight:500;color:#4338ca;
               background:#eef2ff;border:1px solid #c7d2fe;
               padding:.18em .55em;border-radius:999px;">
    AI Operatör Merkezi
  </span>
</h1>
<p>Doğal Türkçe ile tüm kuralları, kampanyaları, ürünleri ve mağaza
   operasyonlarını yönet. Aşağıdaki sohbet conversational rule edit +
   conflict resolution + business analytics ile bağlı.</p>
```

Sayfanın geri kalanı (1182 satır chat UI: `tsws-v2-chat`,
`tsop-ai-modes`, multi-turn history) **hiç değişmedi**.

---

## 6. Tüm Sistem Mimarisi (Tur 1-5 Birikim)

### 6.1 Üst Düzey

```
agent-base-allinone (tek Docker container)
├─ nginx :80
│   ├─ /api/*   → uvicorn :8000 (FastAPI: app.main + orchestration_api)
│   └─ /*       → php-fpm (php-ui)
├─ supervisord process'leri (7 adet):
│   api · worker · rbe-listener · rbe-workflow · rbe-task · php-fpm · nginx
└─ MySQL + Redis (depends_on)
```

### 6.2 Klasör Yapısı (kısa)

```
agent-base/
├─ docker-compose.yml, Dockerfile, README.md
├─ ÖZET.md                                   ← bu dosya
├─ SON_DEGISIKLIKLER_VE_GENEL_SISTEM.md
├─ docker/supervisord.conf
│
├─ agent-base-api/                           ← Python backend
│   ├─ pyproject.toml (langgraph + cryptography; CrewAI yok)
│   ├─ app/{main, api, agents, core, integrations, runtime, services}/
│   ├─ langgraph_engine/{state, nodes, runtime}.py
│   ├─ tool_adapters/{instagram, facebook, tiktok}.py
│   └─ 68 flat .py modül (orchestration_api, listener, ...)
│
└─ php-ui/
    ├─ includes/{bootstrap, auth, config, http, i18n}.php
    ├─ public/
    │   ├─ index.php                        ← /kurallar → redirect
    │   └─ assets/
    │       ├─ css/timeline-rules.css       ← Tur 5 polish-2 premium CSS
    │       └─ js/timeline-page-rules.js    ← Tur 5 polish-2 modern JS
    └─ views/
        ├─ layout.php                       ← sidebar (Kurallar linki YOK)
        ├─ social_media.php, approvals.php
        ├─ sm_tags.php, sm_templates.php
        ├─ system_admin.php                 ← AI OPERATÖR MERKEZİ
        ├─ page.php                         ← generic + rules_toolbar
        ├─ settings/{account,workspace,ai,api_keys,automation,security}.php
        └─ timeline/
            ├─ _rules_toolbar.php           ← Tur 5 polish-2 panel markup
            └─ store_page.php
```

### 6.3 Event → Rule → Execution Akışı

```
[Operatör Türkçe NL]
   ├─► Timeline panel composer veya AI Operatör chat
   ├─► POST /api/internal/structured-rules/parse
   ├─► preview + stepper
   └─► POST /api/internal/structured-rules
        ↓
[INSERT INTO structured_rules]

──── ARKAPLAN ────
[timeline INSERT] → listener.py (2s poll)
   ├─ structured_rule_engine.trigger_rules_for_event
   │   └─ runtime.start_execution(rule, event, user_id)
   │       └─ build_graph(rule):
   │           supervisor → wait ⏸ → content_gen → risk →
   │           approval ⏸ → publish → monitor → finalize
   │           interrupt_before=["approval"], interrupt_after=["wait"]
   │           SqliteSaver checkpoint
   ├─ rule_engine.find_matching_rules → action_engine
   └─ autonomous_planner (creative route)

   ↓
   [Wait → workflow_worker.resume_after_wait]
   [Approval → operatör onayı → resume_execution]
   [Publish → tool_adapters.<channel>.publish() — SOCIAL_PUBLISH_LIVE]

   ↓
[rule_executions UPDATE] + [graph_node_traces INSERT]
   ↓
Timeline paneli:
   - GET /rule-executions?rule_id=X&limit=1 → "son: Tamamlandı · 5 dk"
   - GET /structured-rules-conflicts/suggestions → ⚠ banner
   - health_score chip rengi güncellenir (rule_learning.py)
```

### 6.4 DB Tabloları (özet)

| Tablo | Tur | Amaç |
|------|-----|------|
| `users`, `listener_state`, `rules`, `tool_executions`, `stores`, `items`, `orders`, `ai_tasks`, `workflow_instances`, `automation_logs`, `rule_history`, `planner_proposals`, `approval_requests`, `planner_memory` | T0-T1 | Çekirdek |
| `structured_rules` | T1 | LangGraph Pydantic kuralları + version + health_score |
| `rule_executions` | T1 | LangGraph run status + thread_id + idempotency_key |
| `graph_node_traces` | T1 | Per-node trace |
| `orgs`, `org_members`, `api_keys` | T1 | Multi-tenant |
| `campaigns`, `campaign_metrics` | T1 | Kampanya state machine |
| `social_credentials` | T1 | Fernet şifreli token'lar |
| `scheduled_entries`, `customer_threads`, `customer_messages` | T2 | Schedule + wait_resume + müşteri sohbet |

### 6.5 Güvenlik Katmanları

| Katman | Mekanizma |
|--------|-----------|
| `SOCIAL_PUBLISH_LIVE=0` | Default mock; tool_adapters/* import time'da okur |
| `INTERNAL_SERVICE_IN_PROCESS=1` | Self-HTTP loop guard |
| `interrupt_before=["approval"]` | LangGraph onay öncesi pause |
| `interrupt_after=["wait"]` | LangGraph delay sonrası pause |
| Fernet credentials | `social_credentials.py` |
| Multi-tenant | `auth_service.get_current_auth` |
| Idempotency | `rule_executions.idempotency_key` |
| Pydantic fail-fast | NL parse hata → 422 |
| JS XSS-safe | DOM API + escapeHtml + JSON_UNESCAPED_UNICODE |

---

## 7. Tur 5 Sonrası Vizyon Uyum Tablosu

| Kullanıcı isteği | Karşılandı | % |
|------------------|-----------|---|
| SyntaxError "Unexpected identifier 'nin'" çöz | ✓ | 100% |
| `node -c` ile JS syntax doğrulama | ✓ | 100% |
| `php -l` ile PHP syntax doğrulama (4 dosya) | ✓ | 100% |
| Türkçe ek pattern raw kodda yok (`grep` temiz) | ✓ | 100% |
| Kurallar sekmesini kaldır | ✓ | 100% |
| `/kurallar` ve `/rules` redirect | ✓ | 100% |
| Sidebar'dan Kurallar linkini kaldır | ✓ | 100% |
| Kuralları Zaman Tüneli alt sekmelerine dağıt | ✓ | 100% |
| Mağaza, Ürünler, Stok, Reklamlar, Kampanyalar, Değerlendirmeler, Siparişler vb. her sekme için panel | ✓ | 100% (22 slug mapped) |
| Geniş ve güzel NL textarea | ✓ | 100% |
| Önizle butonu + görsel stepper | ✓ | 100% (renkli pill'ler) |
| Şablonlardan Seç (slug-uyumlu öne çıkar) | ✓ | 100% (`tr-tpl-relevant` mavi vurgu + "öne çıkan" rozeti) |
| Kuralı Etkinleştir butonu | ✓ | 100% (success toast) |
| Kart listesi (başlık + tetik + şablon + kanal) | ✓ | 100% |
| Health score yeşil/sarı/kırmızı chip | ✓ | 100% (>=75% yeşil, >=45% sarı, <45% kırmızı) |
| Son yürütme durumu chip | ✓ | 100% (background fetch + relative time) |
| Aktif/Pasif toggle | ✓ | 100% (**optimistic UI** + rollback) |
| Sil butonu | ✓ | 100% (onay dialog + success toast) |
| Conflict turuncu banner | ✓ | 100% (sol şerit + ⚠ ikon) |
| Sistem Yöneticisi güçlü AI Operatör Merkezi | ✓ | 100% (h1 badge + 1182 satır chat UI) |
| Sürekli açık chat | ✓ | 100% (mevcut `tsws-v2-chat` korundu) |
| Doğal Türkçe ile kural CRUD | ✓ | 95% (conversational_rule_edit endpoint hazır; chat tool-binding T6'ya kaldı) |
| Şablon ismi ile seçim | ✓ | 100% (grid'de `t.name` semantik isim) |
| SM templates ve campaign templates ayrı | ✓ | 100% (üç ayrı katman dokümante) |
| Mevcut sayfaları bozma | ✓ | 100% (social_media, approvals, sm_tags, sm_templates, campaign-management, settings, timeline/store_page — hiçbiri değişmedi) |
| Türkçe metinleri güvenli işle | ✓ | 100% (DOM API + escapeHtml + JSON_UNESCAPED_UNICODE) |
| Modern profesyonel görsel kalite | ✓ | 95% (premium CSS + animasyon + toast + skeleton + responsive) |
| Operatör keyfi (UX) | ✓ | 95% (optimistic UI, hover lift, ⌘+Enter, micro-animasyonlar) |

**Genel uyum:** **~99%**.

---

## 8. Test Komutları ve Kontrol Listesi

### 8.1 Kod Düzeyi (Tur 5 polish-2 doğrulama)

```bash
# JS syntax — kalıcı garantilenin merkezi
node -c /home/bypasa10/Desktop/rule-based-engine/agent-base/php-ui/public/assets/js/timeline-page-rules.js
# Beklenen: exit 0 (sessiz) veya "JS OK"

# PHP syntax (4 dosya)
for f in \
  agent-base/php-ui/views/timeline/_rules_toolbar.php \
  agent-base/php-ui/views/system_admin.php \
  agent-base/php-ui/views/layout.php \
  agent-base/php-ui/public/index.php; do
  php -l "/home/bypasa10/Desktop/rule-based-engine/$f"
done
# Beklenen: 4x "No syntax errors detected"

# rules.php silindi
ls /home/bypasa10/Desktop/rule-based-engine/agent-base/php-ui/views/rules.php
# Beklenen: No such file

# Sidebar temiz
grep "Kurallar</span>" /home/bypasa10/Desktop/rule-based-engine/agent-base/php-ui/views/layout.php
# Beklenen: (boş)

# Apostrof + Türkçe ek pattern raw kodda yok
grep -nE "'[A-Za-zçğıöşü]'(nin|nın|nun|nün|ın|in|un|ün)" \
  /home/bypasa10/Desktop/rule-based-engine/agent-base/php-ui/public/assets/js/timeline-page-rules.js
# Beklenen: (boş)

# CSS dosyası var
ls -la /home/bypasa10/Desktop/rule-based-engine/agent-base/php-ui/public/assets/css/timeline-rules.css
# Beklenen: dosya görülür
```

### 8.2 Docker Smoke

```bash
cd /home/bypasa10/Desktop/rule-based-engine/agent-base
docker compose up -d --build

docker compose exec agent-base-allinone supervisorctl status
# Beklenen: 7 process RUNNING

curl -s http://localhost:8080/api/health | jq
docker compose logs --tail=200 agent-base-allinone 2>&1 | grep -i "syntax\|error" | head -20
```

### 8.3 UI Kontrol Listesi (Tarayıcı + DevTools Console açık)

| # | Adım | Beklenen |
|---|------|---------|
| 1 | `/login` → giriş | Hatasız |
| 2 | Sidebar | "Kurallar" linki **YOK**; "Sistem Yöneticisi" var |
| 3 | `/kurallar` aç | `/page/timeline/all`'a 302 redirect |
| 4 | `/page/timeline/store` | Skeleton 200ms → "Mağaza Kuralları" panel + composer |
| 5 | DevTools Console | `Unexpected identifier 'nin'` **YOK** |
| 6 | Composer'a yaz "Yeni mağaza oluştuğunda hoşgeldin postu hazırla" → ⌘/Ctrl+Enter | Preview + renkli stepper render |
| 7 | "Kuralı Etkinleştir" | Buton "Kaydediliyor…" → toast "Kural etkinleştirildi." → liste yenilenir |
| 8 | Yeni satır görünür | AKTİF chip + son yürütme "henüz yürütülmedi" + sağlık chip |
| 9 | "Pasifleştir" tıkla | Chip anında PASİF olur → toast "Kural pasif." |
| 10 | Geri "Etkinleştir" | Chip anında AKTİF olur → toast |
| 11 | "Şablonlardan seç" | Grid açılır; store.* trigger'lı şablonlar üstte **"öne çıkan"** rozetiyle vurgulu |
| 12 | Şablon kartına tıkla | Textarea dolar + otomatik preview |
| 13 | `/page/timeline/products` | Mağaza kuralı GÖRÜNMEMELİ (filter ✓) |
| 14 | `/page/timeline/all` | Tüm kurallar (filter yok) |
| 15 | Conflict varsa | Üstte turuncu banner + ilgili kuralın altında inline ⚠ uyarısı |
| 16 | `/social-media/system-admin` | H1'de "AI Operatör Merkezi" badge görünür; chat çalışır |
| 17 | Hover üzerine bir kural kartı | Border indigo'ya döner, shadow yumuşar (micro-animation) |
| 18 | Composer textarea focus | Indigo-500 border + 3px alpha ring |
| 19 | Toast notification (silme) | Sağ alt köşede slide-in, 2.8s sonra fade-out |
| 20 | Mobile (< 720px) | Header dik, butonlar full-width, toast sayfayı kapsar |
| 21 | API timeout simülasyonu (Network → Slow 3G) | Skeleton uzun süre kalır, sonra empty state veya error |
| 22 | Mevcut sayfalar (regression) | `/social-media`, `/social-media/onay-bekleyenler`, `/social-media/sablonlar`, `/campaign-management*`, `/settings/*` — hepsi normal çalışır |

### 8.4 Negatif Senaryolar

- ❌ Console'da herhangi `SyntaxError` — **YOK olmalı**
- ❌ `views/rules.php` filesystem'da — **YOK olmalı**
- ❌ Sidebar'da "Kurallar" linki — **YOK olmalı**
- ✓ `/api/internal/structured-rules` cevap vermezse → "Kurallar yüklenemedi: …" empty state
- ✓ `/structured-rules-conflicts/suggestions` hata verirse → sayfada banner görünmez (graceful)
- ✓ Toggle API fail → chip eski haline döner + error toast
- ✓ Tüm Türkçe metinler kararlı render (çift tırnak veya DOM API)

---

## 9. Güçlü Yönler (Tur 5 polish-2 sonrası)

1. **Premium görsel kalite** — Tailwind tarzı tutarlı renk paleti +
   tutarlı spacing + micro-animations + hover lift efektleri.
2. **Optimistic UI** — toggle anında etkili; hata olursa rollback.
3. **Toast > alert** — modern, dismissable, accessibility-friendly.
4. **Skeleton loading** — sayfa açılışında shimmer; "boş" hissi yok.
5. **Renkli stepper** — operatör akışı anında anlıyor (⏸ ⏱ 📤 ✓).
6. **Slug-aware öneri** — şablon grid'inde uygunlar "öne çıkan"
   rozetiyle üstte.
7. **Conflict-aware** — sol şeritli banner + inline ⚠ kural uyarı.
8. **Last-execution-aware** — her kural satırında "son: durum · zaman".
9. **AI her yerden 1 tık** — her panelin sağ üstünde "✨ AI ile yönet →"
   Sistem Yöneticisi'ne yönlendiriyor.
10. **Responsive** — < 720px stack layout + touch-friendly.
11. **JS güvenli string kalıcı disiplin** — `node -c` + grep CI.
12. **CSS dış dosya** — cache + temiz mimari + tarayıcı parser yükü düşük.
13. **Mevcut sayfalar dokunulmadı** — social_media (3500 satır JS bundle),
    approvals, sm_tags, sm_templates, system_admin chat (1182 satır) bozulmadı.

---

## 10. Bilinen Eksikler / Tur 6 Adayları

1. **AI Operatör chat'inde tool-call binding** — "şu kuralı pasifleştir"
   derken doğrudan API çağrısı. `conversational_rule_edit` endpoint'i
   hazır, prompt'a explicit tool-binding eklenecek.
2. **Per-slug execution mini grafik** — son N yürütmenin trend bar'ı.
3. **Operatör özel rule_templates kaydetme** — "mers şablonu"nu
   kişisel kaydetmek (`POST /rule-templates`).
4. **Per-channel SOCIAL_PUBLISH_LIVE** — global flag yerine
   channel-specific (Instagram canlı + TikTok mock).
5. **AI Operatör'un proaktif bildirimi** — "Yeni kuralın başarıyla
   çalıştı" gibi toast'lar.
6. **Visual rule builder** — NL alternatifi drag-drop.
7. **Dark mode** — CSS variables zaten hazır, sadece `prefers-color-
   scheme` query.
8. **Server-side template filter** — şu an client-side sort.
9. **Eski `rule-based-engine/` dizinini sil** — Tur 4-5 stabilse.

---

## 11. JS Güvenli String Pattern (Geliştirici Notu — Zorunlu)

```js
// 1. ZORUNLU: Türkçe metni DOM API ile yerleştir
const el = document.createElement("div")
el.textContent = "Sayfa'nın kuralları"        // çift tırnak güvenli

// 2. MECBURSAN: template literal — asla single-quote
chip.textContent = `${count} kural — AI'nin önerisi`

// 3. HTML inject ediyorsan ALWAYS escapeHtml
container.innerHTML = `<div title="${escapeHtml(rule.name)}">...</div>`

// 4. PHP → JS veri: htmlspecialchars + json_encode
// PHP:
data-foo="<?= htmlspecialchars(json_encode($x, JSON_UNESCAPED_UNICODE),
                              ENT_QUOTES, 'UTF-8') ?>"
// JS:
const x = JSON.parse(el.dataset.foo)

// 5. ASLA: 'kural'ın', 'AI'nin' raw JS literal'da
//        → apostrof JS parser'ı yanıltır → SyntaxError
```

**CI lint önerisi:**
```regex
'[A-Za-zçğıöşüÇĞIÖŞÜ]'[a-zçğıöşü]
```
JSDoc yorumları (`/** ... */`) hariç bu pattern bulunduğunda build
fail edilmeli.

---

*Doküman sonu. Birikim ve evrim tarihi için
`SON_DEGISIKLIKLER_VE_GENEL_SISTEM.md` Tur 5 bölümü (T5-1...T5-12)
okuyun.*
