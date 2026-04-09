# Responsive Design — Analyse & Umstellungsplan

Status: Analyse / Vorschlag
Zielsetzung: Chatsune Frontend mobilfähig machen ("mobile first"), schrittweise,
mit minimaler Backend-Beteiligung.

---

## 1. Ausgangslage (Ist-Stand)

Das Frontend ist aktuell **desktop-only** designt. Befunde:

- **Root-Layout** (`src/app/layouts/AppLayout.tsx`):
  `flex h-full` mit permanent sichtbarer `<Sidebar>` + `<Outlet>`. Kein Burger,
  keine Breakpoint-Logik, keine Drawer-Fallbacks.
- **Sidebar** (`src/app/components/sidebar/Sidebar.tsx`):
  Fest verdrahtete Breiten — Rail `w-[50px]`, Vollansicht `w-[232px]`
  (Zeilen 400, 629). `flex-shrink-0`, kein Hide auf kleinen Viewports.
- **Topbar** (`src/app/components/topbar/Topbar.tsx`):
  Enthält Persona-Pill, Provider-Pill, Jobs-Pill, MEM-Pill. Dicht gepackt,
  ohne Overflow-Strategie.
- **Chat-View** (`src/features/chat/ChatView.tsx`):
  Drei-Spalten-Gefühl — MessageList + ArtefactRail + ArtefactSidebar
  (Zeilen 740–742). Tool-Toggles, Knowledge-Pills, WebSearch-Pills,
  Bookmark-List, Kontext-Pill, Attachment-Strip — alle gleichzeitig
  horizontal im Chat-Header / Footer.
- **Overlays** (UserModal, AdminModal, PersonaOverlay, ModelBrowser,
  LibraryEditor, CurationModal, AvatarCrop):
  Teils bereits mit `sm:`/`md:`-Klassen begonnen — Grep zeigt genau
  **6 Dateien** mit Breakpoint-Prefixes. Der Rest des Codes nutzt
  **keine Tailwind-Breakpoints**.
- **Keine `useMediaQuery` / `matchMedia`-Nutzung** im gesamten Frontend.
- **DnD-Kit** (Drag & Drop) für Personas / Sessions basiert auf
  `pointerWithin` — funktioniert auf Touch grundsätzlich, muss aber
  gegen Scroll-Gesten abgegrenzt werden.
- **Viewport-Meta** in `index.html` bitte prüfen (`width=device-width,
  initial-scale=1`) — falls fehlend, ist das Voraussetzung Nr. 0.

**Backend-Beteiligung:** Das Backend ist weitgehend neutral gegenüber
Viewports. Alle Daten werden über Events/DTOs geliefert; keine
serverseitigen Layout-Entscheidungen. Ein Umbau ist damit
**nahezu backend-frei** machbar. Ausnahmen (siehe §6) sind klein.

---

## 2. Leitplanken / Paradigmen

1. **Mobile First, aber additiv:**
   Basisklassen beschreiben das **Mobile-Layout**, `md:` / `lg:`
   erweitern auf Tablet / Desktop. Keine `max-*`-Breakpoints (rückwärts
   schreiben vermeiden).
2. **Breakpoint-Konvention (Tailwind-Default, nicht überschreiben):**
   - Basis: < 640 px — Phone
   - `sm:` ≥ 640 px — grosses Phone / kleines Tablet (Portrait)
   - `md:` ≥ 768 px — Tablet
   - `lg:` ≥ 1024 px — kleines Desktop (ab hier permanente Sidebar)
   - `xl:` ≥ 1280 px — Desktop (Artefact-Sidebar sichtbar)
3. **Eine Quelle der Wahrheit für "is-mobile":**
   Ein `useViewport()`-Hook (Tailwind-Breakpoints gespiegelt via
   `matchMedia`) für Fälle, in denen CSS allein nicht reicht
   (z. B. Drawer-State, DnD-Deaktivierung, conditional rendering).
4. **Keine separate Mobile-App / kein zweiter Code-Pfad.**
   Eine Code-Base, responsive. Overlays statt Modal-Dialoge auf Mobile
   (Full-screen Sheets).
5. **Touch-First-Interaktionen:**
   Hover-only-Affordances (Pin-Buttons, Delete-Icons beim Hover) müssen
   auf Mobile über Long-Press oder permanente Sichtbarkeit erreichbar
   werden.
6. **Keine Funktionalität ausblenden:**
   Jede Feature muss auf Mobile erreichbar sein — ggf. hinter einem
   zusätzlichen Tap, aber nicht gestrichen.
7. **Performance:**
   Keine doppelten Komponenten-Bäume, kein SSR-Branching. CSS-Toggles
   statt conditional mounts wo möglich.
8. **Visuelle Reduktion auf Mobile & Tablet (entschieden):**
   Farbpalette bleibt erhalten, aber:
   - **weniger Backdrop-Blur** (`backdrop-blur-*` → auf Mobile weg
     oder deutlich schwächer; Performance + Ablenkung)
   - **weniger Gradients** (nur noch dort, wo sie Information tragen,
     z. B. Persona-Avatare; dekorative Flächen werden flach)
   - **weniger Shadows** (grosse `shadow-[0_8px_24px_…]` → kleiner
     oder Border-Fallback)
   - **Font-Umstellung** bleibt erreichbar: Serif / Sans-Serif /
     "white script"-Modus (für Nicht-OLED-Displays wichtig) sind
     auf Mobile genauso zugänglich wie auf Desktop.
   Umsetzung via `md:`-Prefixes: Mobile = flach, `md:backdrop-blur-sm`
   etc. für Tablet/Desktop. Tablet bleibt visuell bei Mobile — dort
   ist die Effekt-Reduktion sogar willkommen.
9. **Zielgeräte-Priorität (entschieden):**
   Phone ist first-class, Tablet "mitgedacht" (gleiches Layout wie
   Phone bis `lg:`, erst ab Desktop-Breakpoint kommt die volle
   Desktop-Experience). Das vereinfacht den Plan erheblich: es gibt
   effektiv nur **zwei** Haupt-Layouts — "kompakt" (< `lg:`) und
   "desktop" (≥ `lg:`).

---

## 3. Ziel-Layout pro Breakpoint

### Phone (< 640 px)
- **Top-App-Bar** (sticky, ca. 48 px): Burger (öffnet Sidebar als
  Drawer), Persona-Name / -Avatar zentriert, Überlauf-Menü rechts
  (Provider, Jobs, MEM als Icons in Dropdown).
- **Sidebar:** Off-Canvas-Drawer von links (volle Breite oder 85 vw),
  Backdrop, swipe-to-close. Rail-Variante entfällt auf Mobile.
- **Chat:** Vollbreit, Nachrichten nehmen 100 % Breite minus Padding.
  ChatInput **sticky bottom**, `env(safe-area-inset-bottom)` beachten.
- **ArtefactSidebar:** als Full-screen Sheet (bottom-sheet oder
  overlay), aufrufbar über Button in Chat-Header.
- **Overlays (UserModal, PersonaOverlay, etc.):** Full-screen Sheets
  statt zentrierter Dialoge. `rounded-none` auf Mobile, `sm:rounded-xl`.
- **Tool-Toggles & Pills:** horizontal scrollbar (`overflow-x-auto`)
  oder in ein kollabierbares Tray.

### Tablet (`sm:` / `md:`)
- **Layout bleibt das Phone-Layout** (Entscheidung: Tablet = kompakt).
  Sidebar weiterhin Drawer, Overlays weiterhin Sheets.
- Einziger Unterschied: Content bekommt grössere Paddings, Persona-
  Grid darf zweispaltig werden (`sm:grid-cols-2`), Sheets dürfen
  eine max-width haben (`sm:max-w-[560px]`), Typografie darf eine
  Stufe grösser.
- Visuelle Effekte (Blur / Gradients / Shadows) bleiben **wie auf
  Mobile reduziert** — erst ab `lg:` kommt die volle Opulenz zurück.

### Desktop (`lg:` und grösser)
- **Ist-Stand bleibt erhalten:** permanente Sidebar (Rail / Voll),
  Topbar inline, ArtefactRail + ArtefactSidebar nebeneinander.
- Nichts Bestehendes wird auf Desktop schlechter.

---

## 4. Fundament / Voraussetzungen (Schritt 0)

Bevor einzelne Views umgebaut werden, muss das Gerüst stehen.

1. **Viewport-Meta-Tag** in `frontend/index.html` verifizieren:
   `<meta name="viewport" content="width=device-width, initial-scale=1,
   viewport-fit=cover">`.
2. **Safe-Area-CSS-Variablen** in `index.css`:
   Nutzung von `env(safe-area-inset-*)` bei sticky Top-/Bottom-Bars.
3. **`useViewport()`-Hook** einführen
   (`frontend/src/core/hooks/useViewport.ts`):
   liefert `{ isMobile, isTablet, isDesktop }` via `matchMedia`
   (Tailwind-Breakpoints gespiegelt). Keine Window-Resize-Listener
   in einzelnen Komponenten.
4. **Drawer-Store** (`useDrawerStore` in `core/store/`):
   Zustand `{ sidebarOpen: boolean, open, close, toggle }`. Persistent
   nur für Desktop-Toggle; auf Mobile default geschlossen.
5. **Globales `min-w-0`-Audit:** Flex-Kinder, die Text enthalten,
   brauchen `min-w-0`, sonst zerreissen lange Titel das Layout
   (verbreiteter Fehler aktuell). Kleine Detail-Runde vor dem Umbau.
6. **Test-Setup:** Chrome DevTools Device-Mode + echtes Gerät
   (iOS Safari + Android Chrome). Playwright-Viewports als optionaler
   smoke-test pro Bereich.

**Aufwand Schritt 0:** klein (0.5 – 1 Tag).

---

## 5. Umbau-Reihenfolge (inkrementell, jede Stufe mergebar)

Jede Stufe ist **eigenständig mergebar** und verbessert das Mobile-
Erlebnis inkrementell. Zwischen den Stufen: Build + manuelles Testen
im DevTools Device Mode.

### Stufe 1 — Shell (AppLayout, Sidebar, Topbar)
**Ziel:** App ist auf Mobile navigierbar, Chat ist erreichbar, Sidebar
als Drawer.

- `AppLayout.tsx`: Sidebar per CSS auf `lg:` persistent, darunter
  Off-Canvas. `fixed inset-y-0 left-0 z-40` + Backdrop + Transform.
- `Sidebar.tsx`: Breiten-Logik anpassen — `w-full sm:w-[85vw] md:w-[320px] lg:w-[232px]`;
  Rail-Variante nur `lg:flex`, sonst `hidden`.
- `Topbar.tsx`: Burger-Button (`lg:hidden`), Pills hinter Overflow-Menü
  (`<details>` oder Custom-Popover) auf Mobile; ab `md:` inline.
- `useDrawerStore` verdrahten, Backdrop schliesst Drawer, `Esc` ebenso,
  Route-Change schliesst Drawer auf Mobile automatisch.

**Akzeptanz:** 360 px Viewport — Login → Persona-Auswahl →
Chat-Session wählen → zurück, alles ohne seitliches Scrollen.

### Stufe 2 — Chat-Kern (MessageList, ChatInput, AttachmentStrip)
**Ziel:** Chatten auf dem Handy ist ergonomisch.

- `MessageList`: horizontale Paddings auf Mobile reduzieren
  (`px-3 md:px-6`), Bubble-Max-Width auf `max-w-[92%] md:max-w-[75ch]`.
- `ChatInput`: sticky bottom, `pb-[env(safe-area-inset-bottom)]`,
  Auto-Grow-Textarea mit `max-h-[40vh]`.
- `AttachmentStrip`: horizontal-scroll auf Mobile, snap-Klassen.
- `ToolToggles` / `KnowledgePills` / `WebSearchPills`: in ein
  kollabierbares "Tools"-Tray packen (Button öffnet Bottom-Sheet
  mit allen Togglen). Auf Desktop bleibt inline.
- `ContextStatusPill`, `JobsPill`, `ProviderPill`: Truncation prüfen,
  `min-w-0` + `truncate`.

**Akzeptanz:** Nachricht senden, Anhang hinzufügen, Tool togglen
auf 360 px — kein Overflow, Tastatur verdeckt Eingabe nicht.

### Stufe 3 — Overlays als Sheets
**Ziel:** Alle Overlays sind auf Mobile nutzbar.

- Gemeinsame `<Sheet>`-Komponente (`core/components/Sheet.tsx`),
  **Eigenbau** (entschieden — keine neue Abhängigkeit):
  Full-screen unter `lg:`, zentriertes Modal ab `lg:`. Einheitliche
  Close-Gesten (Swipe-down per Pointer-Events, `Esc`, Backdrop-Click).
  Kern ist ca. 80–120 Zeilen: Portal + Backdrop + Transform + simple
  Drag-to-Dismiss via `pointerdown`/`pointermove`/`pointerup`.
  Animation via CSS-Transitions, kein Framer-Motion nötig.
- Einzelmigration:
  `UserModal`, `AdminModal`, `PersonaOverlay`, `ModelBrowser /
  ModelConfigModal`, `LibraryEditorModal`, `CurationModal`,
  `AvatarCropModal`, `BookmarkModal`.
- Innere Tab-Navigationen: auf Mobile zu `<select>` oder horizontal
  scroll-snap degradieren.
- `AvatarCropModal`: Touch-Pinch-Zoom verifizieren, ggf. Bibliothek
  konfigurieren.

**Akzeptanz:** Jedes Overlay kann auf 360 px geöffnet, vollständig
bedient und geschlossen werden.

### Stufe 4 — Artefakte & Seitenpanels
**Ziel:** ArtefactSidebar / ArtefactRail sind mobil erreichbar.

- `ArtefactRail`: nur `lg:flex`, darunter Einstiegsbutton im
  Chat-Header.
- `ArtefactSidebar`: als Right-Sheet auf Mobile
  (`fixed inset-y-0 right-0 w-full sm:w-[440px]`).
- `ArtefactOverlay`: Full-screen auf Mobile.

**Akzeptanz:** Artefakt öffnen, Code-Block ansehen, schliessen —
auf Mobile ohne Layout-Bruch.

### Stufe 5 — Pages (Personas, History, Knowledge, Admin, Projects)
**Ziel:** Alle Routen nutzbar.

- `PersonasPage`: Grid `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`,
  Persona-Cards Touch-freundlich (min 44 px Ziele).
- `HistoryPage`: Single-Column-Liste auf Mobile, Filter-Bar
  kollabierbar.
- `KnowledgePage`: Drag-&-Drop-Upload-Zone bleibt, aber Datei-Picker
  Fallback sichtbar. Evtl. Table → Cards auf Mobile.
- `AdminPage`: Tabelle → "Card per Row" unter `md:`, oder horizontal
  scroll mit sticky erster Spalte.
- `ProjectsPage`: analog `PersonasPage`.
- `LoginPage` / `ChangePasswordPage`: quick win, kleinere Paddings,
  volle Breite.

**Akzeptanz:** Jede Route mobil nutzbar, keine horizontalen
Scrollbars auf 360 px.

### Stufe 6 — Touch-Politur
**Ziel:** Fühlt sich nativ an.

- **DnD-Kit auf Mobile deaktivieren oder hinter Long-Press**:
  `PointerSensor` mit `activationConstraint: { delay: 250, tolerance: 5 }`.
  Drag verhindert sonst Scrollen.
- **Hover-only-Affordances** (Pin, Delete, Edit): auf Mobile
  permanent sichtbar **oder** über Context-Menü (Long-Press).
  `@media (hover: none)`-Query nutzen.
- **Tap-Targets**: mindestens 44 × 44 px (WCAG). IconBtn-Komponente
  in Sidebar aktuell 32 × 32 — auf Mobile vergrössern.
- **Scroll-Performance**: `overflow-y: auto; -webkit-overflow-scrolling: touch;`
  (heute Standard, aber prüfen).
- **Focus-Rings** bei Tastatur sichtbar lassen, nur bei `:focus-visible`.

### Stufe 6.5 — Visuelle Reduktion Mobile/Tablet
**Ziel:** Flacher, ruhiger Look unter `lg:`, volle Opulenz ab Desktop.

- Systematisches Grep nach `backdrop-blur`, `bg-gradient-`,
  `shadow-[…]` im Frontend. Jeder Treffer wird zu `md:`/`lg:`-
  scoped (Desktop behält) oder auf Mobile durch eine flache
  Alternative ersetzt (solide Farbe, schmaler Border).
- `index.css`: evtl. eine Utility-Klasse `.surface-flat` für die
  häufigsten Fälle, um Wildwuchs zu vermeiden.
- Font-Picker (Serif / Sans-Serif / White-Script) verifizieren,
  dass er im UserModal auch auf Mobile erreichbar und nutzbar ist.
  White-Script-Option explizit dokumentieren (Non-OLED-Nutzbarkeit).
- Persona-Farben, Chakra-Palette, Gold-Akzente **bleiben unverändert** —
  nur die Effekt-Ebene wird abgespeckt.

**Akzeptanz:** Side-by-Side-Vergleich 360 px vs. 1440 px —
Mobile wirkt ruhig und funktional, Desktop unverändert opulent.

### Stufe 7 — QA & Abschluss
- Vollständiger manueller Durchgang auf iPhone SE (375 px),
  Pixel 5 (393 px), iPad Mini (768 px), iPad Pro (1024 px).
- Build clean (`pnpm run build`, `pnpm tsc --noEmit`).
- Lighthouse Mobile Score ≥ 90 anstreben.
- INSIGHTS.md-Eintrag: Mobile-Entscheidungen dokumentieren.

### Stufe 8 — PWA (Progressive Web App)
**Ziel:** Chatsune lässt sich "Zum Startbildschirm hinzufügen" und
fühlt sich dort wie eine native App an. Wichtig für die weniger
technikaffine Zielgruppe.

- **Web-App-Manifest** (`frontend/public/manifest.webmanifest`):
  Name, Short-Name, Theme-Color (aus Design-System), Background-
  Color, Display `standalone`, Orientation `portrait`, Icon-Set
  (192, 512, maskable).
- **Icons**: bestehendes Chatsune-Logo in den geforderten Grössen
  rendern, `maskable` Variante mit Safe-Area.
- **Service Worker** — bewusst **minimal**: App-Shell (HTML/CSS/JS
  der Vite-Build-Artefakte) cachen, damit die App ohne Netz öffnet
  und einen sinnvollen Offline-Screen anzeigen kann ("Keine
  Verbindung — Nachrichten brauchen Netz"). **Kein** Offline-Chat,
  **kein** Background-Sync (würde das Event-First-Modell brechen).
  Vite-Plugin `vite-plugin-pwa` nutzen — standardisiert, kein
  Eigenbau-Drama hier, weil Service-Worker-Korrektheit heikel ist.
- **iOS-Spezifika**: `apple-touch-icon`, `apple-mobile-web-app-
  capable`, `apple-mobile-web-app-status-bar-style` — iOS ignoriert
  das Manifest teilweise.
- **Install-Prompt**: dezenter Hinweis in der Topbar / im UserModal
  ("App installieren"), erst nach 2. Besuch, mit Opt-Out-Memory.
- **Update-Flow**: wenn der Service Worker eine neue Version findet,
  Toast "Neue Version verfügbar — neu laden".
- **WebSocket-Reconnect** auf Tab-Resume (iOS-Safari-Thema aus §7)
  **hier spätestens** verifizieren und fixen, weil PWA-Nutzer
  die App aggressiver backgrounden.

**Akzeptanz:** Auf iPhone und Android "Zum Startbildschirm" →
App öffnet im Standalone-Modus, Splash-Screen sieht korrekt aus,
Update-Flow funktioniert, Offline-Screen erscheint bei Flugmodus.

### Stufe 9 — Mobile-only Polish (später)
**Ziel:** Native-Feel-Extras. Nicht Teil des initialen Mobile-Rollouts.

- **Kamera-Upload** im Chat: `<input type="file" accept="image/*"
  capture="environment">` als zusätzliche Option neben Datei-Picker.
- **Web Share Target API**: Chatsune als Share-Ziel registrieren,
  damit Nutzer Text/Bilder aus anderen Apps direkt in eine
  Chat-Session teilen können. Erfordert Manifest-Einträge und einen
  Handler-Endpoint im Frontend-Router (`/share-target`), der das
  Shared-Payload in den Chat-Input steckt.
- **Haptic Feedback** (Vibration API) bei Long-Press, Send, Fehler —
  sparsam.
- **Pull-to-Refresh** in Listen (History, Personas) — optional,
  leicht missbraucht; lieber explizite Refresh-Buttons.

---

## 6. Backend-Beteiligung

Minimal, aber nicht null. Kandidaten:

1. **Keine** DTO-/Event-Änderungen notwendig für Layout-Umbau.
2. **Eventuell** ein User-Setting `ui_prefers_compact` — bewusst
   **nicht** empfohlen. Responsive via CSS, kein Serverflag.
3. **Bildgrössen**: Avatare / Persona-Bilder werden heute in
   Originalauflösung ausgeliefert. Für Mobile lohnt ggf. eine
   serverseitige Thumbnail-Variante (z. B. 256 px) — **optionaler
   Follow-Up**, nicht Voraussetzung.
4. **Upload-Limits / Kamera-Integration**: `<input type="file" accept="image/*" capture="environment">` ist rein frontend, Backend akzeptiert Uploads bereits.
5. **WebSocket-Verhalten beim Tab-Sleep (iOS Safari)**: iOS killt
   WS aggressiv im Hintergrund. Reconnect-Logik existiert bereits
   (Redis Streams, `sequence`-basiertes Catchup) — **vor Stufe 1**
   kurz verifizieren, ob sie beim Tab-Resume sauber greift. Falls
   nicht, ist das eine separate Backend-/Infra-Aufgabe.

**Fazit:** 0 Pflicht-Änderungen, 1 Verifikation (WS-Resume), 1
optionaler Follow-Up (Thumbnails).

---

## 7. Risiken / Fallen

- **DnD-Kit + Touch-Scroll-Konflikt** — siehe Stufe 6, Long-Press-Aktivierung ist Pflicht.
- **iOS-Safari 100vh-Bug**: `h-full` auf `<html>` + `<body>` statt
  `h-screen` nutzen; `dvh`/`svh` wo möglich.
- **Tastatur verdeckt ChatInput**: sticky bottom + `dvh` + ggf.
  `VisualViewport`-API für präzise Anpassung.
- **Fixed Widths als Hidden Constraints**: Suche nach `w-[…px]`
  zeigt mindestens 10 Treffer allein in Sidebar. Systematisch durchgehen.
- **Modale mit interner Scroll-Area**: müssen `overscroll-contain`
  setzen, sonst scrollt die Page dahinter mit.
- **Test-Coverage**: Die bestehenden Vitest-Tests (`Sidebar.test.tsx`,
  `PersonaItem.test.tsx`, `NavRow.test.tsx`) prüfen Verhalten, keine
  Viewports. Sie sollten **nicht brechen**. Neue Tests nur bei neuer
  Logik (`useViewport`, Drawer-Store).

---

## 8. Empfohlene Reihenfolge — Zusammenfassung

| Stufe | Scope | Aufwand (grob) | Mergebar |
|------|-------|----------------|----------|
| 0 | Fundament (Hook, Store, Viewport-Meta, min-w-0-Audit) | S | ja |
| 1 | Shell: AppLayout + Sidebar-Drawer + Topbar | M | ja |
| 2 | Chat-Kern: MessageList, ChatInput, Tools-Tray | M | ja |
| 3 | Overlays → Sheet-Komponente | M–L | ja |
| 4 | Artefakte (Rail, Sidebar, Overlay) | S–M | ja |
| 5 | Restliche Pages (Personas, History, Knowledge, Admin, Projects) | M | ja |
| 6 | Touch-Politur (DnD, Hover, Tap-Targets) | S | ja |
| 6.5 | Visuelle Reduktion (Blur/Gradients/Shadows unter `lg:`) | S | ja |
| 7 | QA + Polish | S | ja |
| 8 | PWA (Manifest, Icons, Service Worker, Install-Prompt) | M | ja |
| 9 | Mobile-only Polish: Kamera, Share Target, Haptics (später) | S–M | ja |

Keine Stufe verlässt den Desktop schlechter, als sie ihn vorgefunden hat.
Nach Stufe 1 ist die App **grundsätzlich mobil benutzbar**; alles
danach ist Qualitätssteigerung.

---

## 9. Entscheidungen (von Chris bestätigt)

1. **Primär-Zielgerät: Phone.** Tablet wird mitgedacht, teilt sich
   aber bis `lg:` das Layout mit dem Phone. Keine dritte
   Layout-Stufe.
2. **Sheet-Komponente: Eigenbau.** Keine neue Abhängigkeit (Vaul
   / Radix entfällt). Umfang ca. 80–120 Zeilen, siehe Stufe 3.
3. **PWA: ja.** Eigenständige Stufe 8 — Manifest, Icons, minimaler
   Service Worker (App-Shell-Cache + Offline-Screen), Install-Prompt
   und Update-Flow. Zielgruppe profitiert vom "Zum Startbildschirm
   hinzufügen"-Komfort.
4. **Kamera & Share Target: später (Stufe 9).** Nach der Mobile-
   Basis als Polish-Runde, nicht Teil des initialen Rollouts.
5. **Visuelle Reduktion unter `lg:`: ja.** Farbpalette bleibt,
   Blur / Gradients / Shadows werden stark reduziert. Font-Optionen
   (Serif / Sans-Serif / White-Script für Non-OLED) bleiben auf
   allen Viewports zugänglich. Tablet übernimmt die reduzierte
   Mobile-Ästhetik — die volle Opulenz gibt es erst ab Desktop.
   Eigene Stufe 6.5.

Alle Entscheidungen sind in §2, §3, §5 und in die Stufen-Tabelle
eingearbeitet. Keine offenen Fragen — der Plan kann starten.
