# Pyodide als Client-Side Code-Interpreter — Brainstorming-Zwischenstand

> **Status:** Offene Diskussion, kein Design, keine Implementierung.
> Dies ist ein Denk-Dokument, kein Spec.

---

## Worum geht's

Idee: Dem LLM einen Python-Code-Interpreter zur Verfügung stellen, der
**client-seitig** im Browser des Users läuft. Ziel: Das Modell kann
komplexe mathematische, numerische und analytische Aufgaben lösen, die
es alleine nicht zuverlässig hinbekommt — indem es Python-Code
generiert, der dann tatsächlich ausgeführt wird.

Der Antrieb ist, aus Chatsune von einem "nur Chat" zu einem echten
Analyse-Werkzeug zu machen, ohne am Privacy-Modell zu rütteln: der Code
läuft lokal beim User, nicht auf einem Server.

---

## Was die Architektur heute schon kann

Erfreulich: das Fundament ist bereits gegossen.

- **Tool-Registry** (`backend/modules/tools/_registry.py`) hat schon ein
  `side: "server" | "client"`-Feld in der `ToolGroup`-Dataclass.
  Laut `INSIGHTS.md` INS-010 wurde das **explizit mit Pyodide im
  Hinterkopf** vorbereitet — momentan ist `"client"` ein reiner
  Platzhalter, kein Tool nutzt es.
- **WebSocket-Events** `ChatToolCallStartedEvent` und
  `ChatToolCallCompletedEvent` existieren und das Frontend zeigt sie
  bereits in `ToolCallActivity.tsx` an.
- **Server-seitige Tool-Schleife** (`_inference.py`, `InferenceRunner`)
  funktioniert: LLM-Call → tool_calls einsammeln → ausführen → Ergebnis
  in nächste Iteration reinfüttern → max. 5 Durchläufe.
- **MCP** ist in `CLAUDE.md` erwähnt, aber **nicht implementiert** —
  kein Code, kein Protokoll-Handler. Ist also keine echte Alternative
  im aktuellen Stand.

### Was fehlt
1. Ein **Client-Executor** im Frontend, der `ToolCallEvent`s abfängt,
   Pyodide aufruft und das Ergebnis zurückschickt.
2. Eine Umstellung des `InferenceRunner`, der bei `side: "client"`
   Tools **nicht lokal ausführt**, sondern ein
   `tool.forwarded-to-client`-Event emittiert, **pausiert**, und auf
   eine `tool.result`-Nachricht vom Client wartet, bevor die nächste
   LLM-Iteration startet.
3. Eine konkrete `ToolGroup` für den Python-Interpreter mit
   `side: "client"`.

Das ist architektonisch machbar, aber der Punkt (2) — Server pausiert
auf Client-Antwort — ist die **bedeutendste strukturelle Änderung**
und sollte nicht unterschätzt werden.

---

## Die verglichenen Optionen

| Option | Was | Vorteil | Nachteil |
|---|---|---|---|
| **Pyodide (Browser)** | Voller Python-Stack in WASM | numpy/pandas/scipy/sympy/matplotlib — echtes Ökosystem. Daten verlassen den Browser nie. | Initial ~6-10 MB, Libs on demand. Start-Cost. |
| **QuickJS / JS-Sandbox** | LLM generiert JS statt Python | ~100 KB statt 10 MB. LLMs sind in JS-Code-Gen empirisch etwas stärker. | Kein numpy/pandas-Ökosystem. Mathematik-/Analytik-Libs in JS sind dünn. |
| **Server-side Sandbox** (E2B, Deno, Docker) | Code läuft auf Server | LLMs sind darauf trainiert (ChatGPT Code Interpreter). | User-Daten müssen raus aus dem Browser → **bricht das Privacy-Modell**. |
| **MicroPython im Browser** | Mini-Python | Winzig. | Kein numpy/scipy — nur "Taschenrechner". |

**Tentative Empfehlung:** Pyodide. Das Privacy-Argument ist bei Chatsune
scharf, und `numpy`/`pandas`/`sympy` sind echte Hebel, die ein
JS-Sandbox nicht ersetzt. Aber: *ist nicht committed*.

---

## Realitäts-Check: Caching & Start-Cost

Pyodide ist gross. Entscheidend für die UX ist, wie oft dieser Cost anfällt.

- **HTTP-Cache:** `pyodide.js`, `pyodide.asm.wasm`, und alle
  Package-Wheels werden bei korrekter Konfiguration (self-hosted,
  `Cache-Control: immutable`) einmal geladen und danach nie wieder
  übers Netz.
- **Service Worker + Cache API** machen das zusätzlich offline-fest.
- **Was pro Page-Load *nicht* gecached werden kann:** WASM muss neu
  instanziiert und der Python-Interpreter neu hochgefahren werden.
  Das kostet ~1-2 s selbst bei heissem Cache. Hinzu kommt
  `loadPackage()` pro Lib die in *dieser* Session zum ersten Mal
  gebraucht wird (~1-3 s pro Lib, im RAM, nicht übers Netz).

**Grobe Richtwerte:**
- Erster Besuch überhaupt: ~8-15 s bis Pyodide + Standard-Libs warm.
  Einmalig.
- Folge-Besuche: ~2-4 s bis Pyodide warm. Libs lazy dazu.
- Innerhalb einer Session: instant.

**Mitigationen, die man einbauen würde:**
1. **Self-hosting** (nicht vom CDN), damit man Cache-Header kontrolliert.
2. **Background-Warmup:** Pyodide wird nach dem Login still im Web
   Worker hochgefahren, bevor der User das Tool zum ersten Mal
   braucht.
3. **Lazy Package Loading:** `numpy`/`pandas`/etc. erst bei
   erstem `import`.
4. **Narrative Abdeckung:** Ein "LLM nutzt Python"-Badge mit
   Fortschrittsanzeige macht die ersten 2-3 s erklärbar.

---

## Der Scope-Punkt, der Chris gestoppt hat

Ursprünglicher Gedanke war "Pyodide als Tool anflanschen". In der
Diskussion kam heraus, dass die Zielrichtung **Full Code Interpreter
à la ChatGPT/Claude** ist — also die ambitionierteste Variante.
Das ist kohärent, aber kein kleines Feature. Es berührt:

- Backend: neue Tool-Call-Semantik (Server wartet auf Client)
- Frontend: Web-Worker-Host, Pyodide-Runtime, Output-Rendering
- Artefakt-System: wenn der Interpreter Plots oder Dateien erzeugt,
  müssen die als Artefakte im Chat auftauchen
- Security-Modell: Sandbox-Grenzen, Timeouts, Resource-Limits
- UX: Fortschritts-Anzeige, Fehler-Darstellung, "Python läuft"-State

Das ist der Moment, in dem "mal eben Pyodide reinstöpseln" zu
"eigenständiges Teilprojekt" wird.

---

## Offene Fragen, über die Chris nachdenken will

Diese sind die Haupt-Entscheidungs-Hebel. Ohne Antwort kein Design.

### 1. Scope-Ehrlichkeit
Ist das Ziel wirklich **E) Full Code Interpreter**, oder reicht für den
ersten Schritt eine kleinere Variante (A-D aus der Diskussion)? Das
ist keine technische, sondern eine Produkt-Frage.

- **A** Pure Math / Symbolic (`sympy`, `numpy`) — ~3 MB, klein
- **B** Numerik & Statistik (`numpy`, `scipy`) — ~15 MB, mittel
- **C** Datenanalyse (`pandas`/`polars` + Artefakt-Bridge) — ~8 MB + Infra
- **D** Visualisierung (`matplotlib` + Rendering) — komplex
- **E** Alles davon, Code Interpreter — Teilprojekt

### 2. Namespace-Lifetime
Wenn es E) wird: soll der Python-Namespace **innerhalb einer
Chat-Session persistent** sein?

- **A) Persistent** — LLM kann in Call #1 `df = pd.read_csv(...)`
  machen und in Call #3 noch darauf zugreifen. Jupyter-Feeling.
  Problem: Reload = Zustand weg, nicht rehydratierbar.
- **B) Frisch pro Call** — jeder Call leerer Namespace. Robust,
  aber tokenfressend und schwächer.
- **C) Persistent + resettbar + Reload-tolerant** — wie A), aber mit
  explizitem Reset und stillem Neu-Init bei Reload.

### 3. Daten-Bridge
Soll der Interpreter Zugriff auf **User-Uploads und Chat-Artefakte**
haben? Ohne das ist C) aus (1) nicht möglich. Das bedeutet:
Frontend muss Files aus dem Artefakt-System in den Pyodide-Worker
injizieren.

### 4. Output-Kanäle
Was zählt als "Ergebnis" eines Tool-Calls?
- `stdout` + `return value` (einfach)
- **Plus** erzeugte Bilder (matplotlib PNG) → müssen zu Artefakten werden
- **Plus** erzeugte Dateien (CSV-Export) → müssen downloadbar sein
- **Plus** strukturierte Tabellen (DataFrame.to_dict) → müssen im Chat gerendert werden

### 5. Sandbox & Limits
- Timeout pro Tool-Call? (z.B. 30 s; Worker terminieren bei Überschreitung)
- Speicher-Limit?
- Netzwerk-Zugriff aus Pyodide? (Default: **nein** — `pyodide.http` nicht aktivieren)
- Was passiert, wenn der LLM in eine Endlos-Schleife generiert?

### 6. Wartesemantik im Server
Wie lange darf der `InferenceRunner` auf eine Client-Tool-Antwort
warten, bevor er aufgibt? Was, wenn der User mittendrin die
WebSocket-Verbindung verliert? Wer cleant den hängenden State auf?

### 7. Erst-Besuch-Kosten
Ist die ~8-15 s Initial-Load akzeptabel, oder muss das Feature
opt-in sein (User schaltet in den Settings "Code Interpreter aktivieren"
und akzeptiert damit den Download)?

---

## Was der nächste Schritt *nicht* ist

- Nicht implementieren.
- Nicht anfangen, Dependencies zu installieren.
- Nicht eine Tool-Group registrieren.
- Nicht das Frontend anfassen.

---

## Was der nächste Schritt *ist*

Chris denkt über die Fragen oben nach (besonders 1, 2, 7 — die
Produkt-Entscheidungen) und kommt zurück. Dann gehen wir in die
Design-Phase mit einer klaren Richtung.
