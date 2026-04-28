# Chatsune — Datenmodell für die E2EE-Analyse (Version 0.1.0)

Stand: 2026-04-28. Quelle: alle `_models.py` und `_repository.py` unter `backend/modules/`,
plus `backend/jobs/_models.py`. Diese Datei listet **jede Property aller persistierten
Objekte** und bewertet, ob sie für End-to-End-Encryption (E2EE) berücksichtigt werden
sollte.

## Zweck

Vorbereitung auf das E2EE-Feature von 0.1.0. Diese Datei ist die Grundlage für:

1. **Schritt 1 — diese Analyse:** Eine vollständige Liste aller Properties, mit
   einer Vor-Einschätzung, ob die Property zu verschlüsseln ist. Side-Channel-Leaks
   werden explizit aufgeführt (Reviewer-Fokus).
2. **Schritt 2 (User-Review):** Side-Channel-Leaks prüfen — was könnte trotz
   verschlüsseltem Content noch über Metadaten / Indizes / Aggregationen leaken.
3. **Schritt 3 (separate Session):** Machbarkeit pro Property — viele
   "Encrypt: Ja"-Entscheidungen erfordern Funktionsänderungen (z. B.
   Server-Volltextsuche entfällt, Vektor-Search entfällt oder wandert auf
   den Client, Sortierung über verschlüsselte Felder unmöglich).

## Spaltenbedeutung der Tabellen

| Wert | Bedeutung |
|---|---|
| **Ja** | User-Content oder PII. Klarer E2EE-Kandidat. |
| **Nein** | Server muss lesen können (Auth, Routing, Ownership, Scheduler). |
| **Side-channel** | Auch wenn Hauptinhalt verschlüsselt ist, leakt diese Property Information (Größe, Timing, Beziehung, Topic-Hint, Status). Reviewer-Aufmerksamkeit. |
| **Fernet (server)** | Heute bereits mit serverseitigem Fernet verschlüsselt (`backend.config.settings.encryption_key`). Für echtes E2EE muss der Schlüsselbund auf User-DEK umgestellt werden. |
| **Schlüsselmaterial** | IST das Schlüsselmaterial — nicht zu verschlüsseln, sondern Bestandteil der E2EE-Foundation. |

`user_id` taucht in fast jedem Document auf. Es ist immer **Nein** (Ownership-Filter,
Indizes, Cascade-Delete). Im Folgenden wird das nicht jedes Mal wiederholt, wenn die
Begründung trivial ist.

---

## 1. Modul `chat`

### Collection `chat_sessions`

Quelle: `backend/modules/chat/_repository.py:42-63` (anlegen) und diverse
`update_session_*`. Das `_models.py` ist veraltet — die echte Shape ergibt sich
aus dem Repository.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Session-ID | Nein | Routing, FK aus messages. |
| `user_id` | str | Owner | Nein | Ownership-Filter. |
| `persona_id` | str | Welche Persona | **Side-channel** | Verlinkt Topic/Persönlichkeit; durch Aggregation kann man Häufigkeit pro Persona ableiten. |
| `state` | enum | idle / streaming / requires_action | Nein | Server-Logik. |
| `pinned` | bool | Pinned-Flag | Nein | Sortierreihenfolge. Aber: *welche* Session gepinnt ist, ist Metadata. |
| `title` | str | Auto-generierter Titel (LLM) | **Ja** | Faßt Inhalt zusammen — größter Leak im Modell. |
| `tools_enabled` | bool | Tools an? | **Side-channel** | Pro-Session-Setting; korreliert mit Use-Case. |
| `auto_read` | bool | TTS-Auto-Wiedergabe | Side-channel | Vorlieben. |
| `reasoning_override` | bool \| null | Pro-Session-Override | Nein | Server-Routing. |
| `knowledge_library_ids` | list[str] | Welche Libraries angeheftet | **Side-channel** | Topic-Hint (z. B. "medizinische Library"). |
| `context_status` | str | green/yellow/red | Side-channel | Leakt Konversationslänge. |
| `context_fill_percentage` | float | Token-Fill % | **Side-channel** | Größenleak. |
| `context_used_tokens` | int | Absolute Tokens | **Side-channel** | Größenleak. |
| `context_max_tokens` | int | Modell-Limit | Nein | Modell-Property. |
| `deleted_at` | datetime \| null | Soft-Delete | Nein | Server-Cleanup. |
| `created_at` | datetime | | Side-channel | Timing-Korrelation. |
| `updated_at` | datetime | | Side-channel | Aktivitätsmuster. |

### Collection `chat_messages`

Quelle: `backend/modules/chat/_repository.py:376-435` (`save_message`).
Die `_models.py`-Version ist unvollständig.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Message-ID | Nein | FK aus bookmarks. |
| `session_id` | str | FK | Nein | Server-Routing. |
| `user_id` | str | Owner (denormalisiert) | Nein | Index für Korrelations-Lookup. |
| `role` | enum | user / assistant / tool | **Side-channel** | Verteilung user vs. assistant lässt Aktivitäts-Muster leaken. |
| `content` | str | Nachrichten-Text | **Ja** | Kerncontent. Achtung: heute existiert `content_text` Volltextindex und `content` Regex-Suche → ohne Funktionsänderung nicht verschlüsselbar. |
| `thinking` | str \| null | Reasoning-Output des Modells | **Ja** | Modell-Reasoning, oft sehr persönlich. |
| `token_count` | int | | **Side-channel** | Größenleak. |
| `web_search_context` | list[dict] | Such-Treffer (title, url, snippet, source_type) | **Ja** | Was wurde gesucht und gefunden. |
| `knowledge_context` | list[dict] | Knowledge-Chunks, die in den Prompt geflossen sind | **Ja** | Inhalt aus Libraries. |
| `pti_overflow` | dict \| null | Token-Overflow-Info | Side-channel | Diagnostik. |
| `attachment_ids` | list[str] | FK auf storage_files | Nein | Routing. Die Anzahl/Existenz ist Side-channel. |
| `attachment_refs` | list[dict] | Snapshot (file_id, display_name, media_type, size_bytes, thumbnail_b64, text_preview) | **Ja** | `display_name`, `text_preview`, `thumbnail_b64` sind Content. |
| `vision_descriptions_used` | list[dict] | Vision-Beschreibungen pro Datei (file_id, display_name, model_id, text) | **Ja** | LLM-Beschreibung des Bildinhalts. |
| `artefact_refs` | list[dict] | (artefact_id, handle, title, artefact_type, operation) | **Ja** | `title`, `handle` sind Content. |
| `tool_calls` | list[dict] | (tool_call_id, tool_name, arguments, success, moderated_count) | **Ja** | `arguments` enthalten User-Input (z. B. Suchbegriffe). `tool_name` ist Side-channel. |
| `image_refs` | list[dict] | (id, blob_url, thumb_url, width, height, prompt, model_id, tool_call_id, thumbnail_b64) | **Ja** | `prompt`, `thumbnail_b64` sind Content. |
| `refusal_text` | str \| null | Refusal-Text | **Ja** | Topic-Leak (was wurde abgelehnt). |
| `usage` | dict \| null | Token/Cost-Counter | Side-channel | Größenleak. |
| `status` | enum | completed / aborted / refused | Side-channel | Refusal-Häufigkeit leakt Topics. |
| `correlation_id` | str \| null | Logische Operation | Nein | Server-Tracing. |
| `extracted_at` | datetime \| null | Memory-Extraction-Marker | Nein | Job-Status. |
| `created_at` | datetime | | Side-channel | Timing. |
| `updated_at` | datetime | (bei Edit) | Side-channel | Edit-Aktivität. |

> **Index-Warnung:** `content_text` ist ein MongoDB Volltextindex auf `content`,
> und in `search_sessions` läuft Regex über `title`. Beide Pfade sind mit E2EE
> nicht kompatibel — Schritt 3 muss entscheiden, ob server-Suche entfällt oder
> auf client-seitige Indizes umgestellt wird.

---

## 2. Modul `bookmark`

### Collection `bookmarks`

Quelle: `backend/modules/bookmark/_models.py`, `_repository.py:18-40`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Bookmark-ID | Nein | |
| `user_id` | str | Owner | Nein | |
| `session_id` | str | FK | Nein | Cascade. |
| `message_id` | str | FK | Nein | Cascade. |
| `persona_id` | str | FK | Side-channel | Wie bei sessions. |
| `title` | str | User-/auto-generierter Titel | **Ja** | Content. |
| `scope` | enum | global / local | Side-channel | Sichtbarkeitsebene. |
| `display_order` | int | | Nein | Sortierung. |
| `created_at` | datetime | | Side-channel | Timing. |

---

## 3. Modul `project`

### Collection `projects`

Quelle: `backend/modules/project/_models.py`, `_repository.py:19-41`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Project-ID | Nein | |
| `user_id` | str | Owner | Nein | |
| `title` | str | | **Ja** | Content. |
| `emoji` | str \| null | Emoji-Icon | **Ja** | User-Wahl, Topic-Hint. |
| `description` | str | | **Ja** | Content. |
| `nsfw` | bool | NSFW-Flag | **Side-channel** | Topic-Leak. |
| `pinned` | bool | | Nein | Sortierreihenfolge-Logik. |
| `sort_order` | int | | Nein | |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

---

## 4. Modul `persona`

### Collection `personas`

Quelle: `backend/modules/persona/_models.py`, `_repository.py:19-60`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Persona-ID | Nein | |
| `user_id` | str | Owner | Nein | |
| `name` | str | Persona-Name | **Ja** | Content. |
| `tagline` | str | Kurzbeschreibung | **Ja** | Content. |
| `model_unique_id` | str \| null | `{connection}:{slug}` | **Side-channel** | Welches Modell eine Persona benutzt. Bei Cascading slug-rename zeigt der Cascade-Pfad ein Pattern: erst Plain-DB-Lookup nötig. |
| `system_prompt` | str | System-Prompt | **Ja** | Sehr persönlich, oft sensibel. |
| `temperature` | float | | Nein | Modell-Parameter. |
| `reasoning_enabled` | bool | | Nein | Modell-Parameter. |
| `soft_cot_enabled` | bool | | Nein | |
| `vision_fallback_model` | str \| null | | Side-channel | Modellwahl. |
| `nsfw` | bool | | **Side-channel** | Topic-Leak. |
| `use_memory` | bool | | Nein | Feature-Flag. |
| `colour_scheme` | str | UI-Theme | Nein | Cosmetic. |
| `display_order` | int | | Nein | |
| `monogram` | str | Initialen | **Ja** | Aus `name` abgeleitet — wenn `name` Ja, dann auch hier. |
| `pinned` | bool | | Nein | |
| `profile_image` | str \| null | URL/Blob-ID auf storage | **Ja** (Inhalt) / Side-channel (ID) | Das Bild selbst muss verschlüsselt im Blob-Store liegen. |
| `profile_crop` | dict \| null | Crop-Koordinaten | Side-channel | Cosmetic, harmlos. |
| `mcp_config` | dict \| null | MCP-Server-Config | **Ja** | Kann URLs / Geheimnisse enthalten. |
| `voice_config` | dict \| null | (auto_read, roleplay_mode, …) | Side-channel | Vorlieben. |
| `integration_configs` | dict[str, dict] | Pro-Integration-Config | **Ja** | Inhalt — `voice_id`, modell-spezifische Auswahl. |
| `integrations_config` | dict \| null | Allowlist enabled_integration_ids | **Side-channel** | Welche Tools die Persona benutzt. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

> Das Modell hat zusätzlich `knowledge_library_ids` (siehe `remove_library_from_all_personas`)
> auch wenn das Schema-Modell es nicht listet — das ist eine Liste von Library-FKs:
> **Side-channel** (welche Wissensgebiete gehören zu welcher Persona).

---

## 5. Modul `memory`

### Collection `memory_journal_entries`

Quelle: `backend/modules/memory/_models.py`, `_repository.py:26-53`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `persona_id` | str | FK | Side-channel | |
| `content` | str | Memory-Snippet | **Ja** | Sehr persönlich. |
| `category` | str \| null | | **Side-channel** | Topic-Leak. |
| `source_session_id` | str | FK | Nein | Cascade. |
| `state` | enum | uncommitted / committed / archived | Nein | Job-State. |
| `is_correction` | bool | | Side-channel | |
| `archived_by_dream_id` | str \| null | FK | Nein | |
| `auto_committed` | bool | | Side-channel | |
| `created_at` | datetime | | Side-channel | |
| `committed_at` | datetime \| null | | Side-channel | |

### Collection `memory_bodies`

Quelle: `backend/modules/memory/_models.py`, `_repository.py:227-267`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `persona_id` | str | FK | Side-channel | |
| `content` | str | Konsolidierte Memory | **Ja** | Quasi: das Gedächtnis des Users. |
| `token_count` | int | | **Side-channel** | Größenleak. |
| `version` | int | | Nein | Versionierungslogik. |
| `entries_processed` | int | | Side-channel | Aktivitätsmaß. |
| `created_at` | datetime | | Side-channel | |

---

## 6. Modul `knowledge`

Es gibt kein `_models.py` — Quelle: `backend/modules/knowledge/_repository.py`.

### Collection `knowledge_libraries`

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `name` | str | | **Ja** | Content. |
| `description` | str \| null | | **Ja** | Content. |
| `nsfw` | bool | | **Side-channel** | Topic-Leak. |
| `document_count` | int | | Side-channel | Größenleak. |
| `default_refresh` | str | standard / aggressive / off | Side-channel | Vorliebe. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `knowledge_documents`

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `library_id` | str | FK | Nein | |
| `title` | str | | **Ja** | Content. |
| `content` | str | Volltext des Dokuments | **Ja** | Kerncontent. |
| `media_type` | str | MIME-Type | **Side-channel** | Welche Datei-Arten. |
| `size_bytes` | int | | **Side-channel** | Größenleak. |
| `chunk_count` | int | | Side-channel | |
| `embedding_status` | enum | pending / embedded / error | Nein | Job-State. |
| `embedding_error` | str \| null | Letzter Fehler | **Ja** | Kann Text-Snippets enthalten. |
| `retry_count` | int | | Nein | |
| `trigger_phrases` | list[str] | RAG-Trigger | **Ja** | User-definierte Schlagwörter, sehr topic-leakend. |
| `refresh` | str \| null | | Nein | |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `knowledge_chunks`

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `document_id` | str | FK | Nein | |
| `library_id` | str | FK (denormalisiert) | Nein | |
| `text` | str | Chunk-Text | **Ja** | Content. |
| `heading_path` | list[str] | Heading-Hierarchie | **Ja** | Content (Markdown-Headings). |
| `preroll_text` | str | Kontext-Vorlauf | **Ja** | Content. |
| `chunk_index` | int | | Nein | |
| `token_count` | int | | Side-channel | |
| `vector` | list[float] (768d) | Arctic-Embed-M v2.0 | **Ja** *und* **Side-channel** | Reversiert nicht trivial in Klartext, lässt aber Nähe zu anderen Vektoren erkennen → semantische Topic-Cluster sichtbar. Vector-Search läuft serverseitig (`$vectorSearch`) → mit E2EE inkompatibel; entweder Embeddings clientseitig oder Funktion entfällt. |
| `created_at` | datetime | | Side-channel | |

> **Index-Warnung:** Vector-Search-Index `knowledge_vector_index` filtert über
> `user_id` und `library_id`. Wenn der Vektor verschlüsselt wird, geht
> Server-Vector-Search verloren.

---

## 7. Modul `user`

### Collection `users`

Quelle: `backend/modules/user/_models.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | User-ID | Nein | Ownership-Schlüssel. |
| `username` | str | Login-Name | Nein | Lookup-Schlüssel für Login. |
| `email` | str | E-Mail | **Nein** | Aktuell für Login/Recovery — falls E2EE-würdig: **Ja**, aber Recovery-Flow muss Alternative kennen. **Side-channel** falls beibehalten, da PII. |
| `display_name` | str | UI-Name | **Ja** | PII / User-Wahl. Server braucht ihn nicht. |
| `password_hash` | str | Argon2id | Nein | Server-Verifikation. |
| `password_hash_version` | int \| null | KDF-Version | Nein | |
| `role` | enum | master_admin / admin / user | Nein | Server-Authz. |
| `is_active` | bool | | Nein | Server-Authz. |
| `must_change_password` | bool | | Nein | Server-Authz. |
| `recent_emojis` | list[str] | Picker-State | **Ja** | User-Vorliebe. Server braucht es nicht. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `user_keys`

Quelle: `backend/modules/user/_models.py:45-58`, `_key_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `user_id` | str | Owner | Nein | Lookup. |
| `kdf_salt` | bytes(32) | Argon2-Salt | **Schlüsselmaterial** | Bestandteil der KDF-Foundation. |
| `kdf_params` | object | (memory_kib, iterations, parallelism) | Nein | Server muss KDF-Parameter kennen. |
| `current_dek_version` | int | | Nein | Routing. |
| `deks` | dict[str, WrappedDekPair] | wrapped_by_password / wrapped_by_recovery | **Schlüsselmaterial** | Sind die *gewrappten* DEKs — Inhalt ist bereits Cipher. |
| `dek_recovery_required` | bool | Recovery-Modus | Nein | Server-Logik. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | Key-Rotation-Zeitstempel. |

### Collection `audit_log`

Quelle: `backend/modules/user/_audit.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `timestamp` | datetime | | Nein | Audit-Pflicht. |
| `actor_id` | str | Wer hat es getan | Nein | Audit-Pflicht. |
| `action` | str | Action-Code | Nein | Audit-Pflicht. |
| `resource_type` | str | | Nein | Audit-Pflicht. |
| `resource_id` | str \| null | | Side-channel | FK, leakt Aktivität. |
| `detail` | dict \| null | Frei strukturierte Details | **Ja** | Kann User-Content enthalten (Diff von Edit, Werte). Genaue Felder müssen beim Logging gefiltert werden — heute ist `detail` ein Catch-All. |

> **Architektur-Kollision:** Audit-Log soll Server-Operations dokumentieren —
> wenn User-Content per E2EE blind ist, kann ein Admin auch den Audit-Log nicht
> mehr sinnvoll lesen. Schritt 3-Diskussion: was bleibt im Klartext für Audit,
> was wird redacted.

### Collection `invitation_tokens`

Quelle: `backend/modules/user/_invitation_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | ObjectId | | Nein | |
| `token` | str (URL-safe random) | Plaintext-Token | Nein | Wird per Index gefunden — Server muss matchen. **Sicherheit: kurze TTL (24h), passt schon.** |
| `created_at` | datetime | | Side-channel | |
| `expires_at` | datetime | | Nein | TTL-Index treibt Cleanup. |
| `used` | bool | | Nein | |
| `used_at` | datetime \| null | | Side-channel | |
| `used_by_user_id` | str \| null | | Nein | |
| `created_by` | str | Admin-User-ID | Nein | Audit. |

> Kein User-Content. E2EE-irrelevant.

---

## 8. Modul `storage`

### Collection `storage_files`

Quelle: `backend/modules/storage/_models.py`, `_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | File-ID | Nein | |
| `user_id` | str | Owner | Nein | |
| `persona_id` | str \| null | FK | Side-channel | Welche Persona zugeordnet ist. |
| `original_name` | str | Dateiname beim Upload | **Ja** | Content. |
| `display_name` | str | UI-Name | **Ja** | Content. |
| `media_type` | str | MIME | **Side-channel** | Welche Dateitypen (Bild, Audio, Doc). |
| `size_bytes` | int | | **Side-channel** | Größenleak. |
| `file_path` | str | Relativer Pfad im Volume | Nein | Server muss laden können. **Aber:** Pfadstruktur `{user_id}/{uuid}.bin` leakt nichts mehr als `user_id` selbst. |
| `thumbnail_b64` | str \| null | Inline-Thumbnail (klein) | **Ja** | Bild-Content (Miniatur). |
| `text_preview` | str \| null | Erste paar Zeilen Doc-Inhalt | **Ja** | Content. |
| `vision_descriptions` | dict[model_id, {text, model_id, created_at}] | LLM-Beschreibungen | **Ja** | LLM-generierter Bildinhalt. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

> **Blob-Storage:** Die eigentlichen Dateien liegen unter `file_path` im
> Storage-Volume. Diese müssen **separat** verschlüsselt werden (siehe Abschnitt
> "Blobs außerhalb MongoDB").

---

## 9. Modul `llm`

### Collection `llm_connections`

Quelle: `backend/modules/llm/_connections.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | Connection-ID | Nein | |
| `user_id` | str | Owner | Nein | |
| `adapter_type` | str | ollama_http / community / xai / mistral / nano_gpt … | **Side-channel** | Welche Backends genutzt werden. |
| `display_name` | str | UI-Label | **Ja** | User-Wahl. |
| `slug` | str | URL-safe | **Ja** | User-Wahl, oft beschreibend. |
| `config` | dict | Plain-Config (URL, max_parallel, …) | **Ja** | Enthält endpoint-URL, oft selbstgehostete Adresse → leakt Infrastruktur. |
| `config_encrypted` | dict[str, base64-Fernet] | Geheime Felder (api_key, …) | **Fernet (server)** | Heute Server-Fernet — für E2EE auf User-DEK umstellen. |
| `last_test_status` | str \| null | ok / failed | Side-channel | |
| `last_test_error` | str \| null | Fehlermeldung | **Ja** | Kann URL/Key-Hints enthalten. |
| `last_test_at` | datetime \| null | | Side-channel | |
| `is_system_managed` | bool | Vom Homelab gemanagte Self-Connection | Nein | Server-Logik. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `llm_user_model_configs`

Quelle: `backend/modules/llm/_user_config.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `model_unique_id` | str | `{conn_slug}:{model}` | **Side-channel** | Welche Modelle der User benutzt. |
| `is_favourite` | bool | | Side-channel | |
| `is_hidden` | bool | | Side-channel | |
| `custom_display_name` | str \| null | | **Ja** | User-Wahl. |
| `custom_context_window` | int \| null | | Nein | Routing-Override. |
| `custom_supports_reasoning` | bool \| null | | Nein | Routing-Override. |
| `notes` | str \| null | Eigene Notizen | **Ja** | Content. |
| `system_prompt_addition` | str \| null | Eigene Prompt-Erweiterung | **Ja** | Content. |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `llm_homelabs`

Quelle: `backend/modules/llm/_homelabs.py:HomelabRepository`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | implicit ObjectId | | Nein | |
| `user_id` | str | Owner | Nein | |
| `homelab_id` | str | Public ID | Nein | Sidecar-Auth. |
| `display_name` | str | UI-Label | **Ja** | User-Wahl. |
| `host_key_hash` | str (sha256) | Hash des Host-Keys | Nein | Lookup beim Sidecar-Connect. **Hash, nicht Plaintext.** |
| `host_key_hint` | str (4 chars) | Letzte 4 Zeichen | **Side-channel** | Mini-Leak. |
| `status` | str | active / disabled | Nein | |
| `created_at` | datetime | | Side-channel | |
| `last_seen_at` | datetime \| null | | **Side-channel** | Aktivitäts-Heartbeat. |
| `last_sidecar_version` | str \| null | | Side-channel | Software-Version-Leak. |
| `last_engine_info` | dict \| null | Engine-Metadaten | **Ja** | Kann Modell-Liste / Hardware enthalten. |
| `max_concurrent_requests` | int | | Nein | Server-Semaphore. |
| `host_slug` | str \| null | Self-Connection-Slug | **Ja** | User-Wahl. |

### Collection `llm_homelab_api_keys`

Quelle: `backend/modules/llm/_homelabs.py:ApiKeyRepository`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | implicit ObjectId | | Nein | |
| `homelab_id` | str | FK | Nein | |
| `user_id` | str | Owner | Nein | |
| `api_key_id` | str | Public-ID | Nein | |
| `display_name` | str | | **Ja** | User-Wahl. |
| `api_key_hash` | str (sha256) | | Nein | Lookup. |
| `api_key_hint` | str | | **Side-channel** | |
| `allowed_model_slugs` | list[str] | | **Side-channel** | Welche Modelle freigegeben sind. |
| `status` | str | active / revoked | Nein | |
| `created_at` | datetime | | Side-channel | |
| `revoked_at` | datetime \| null | | Side-channel | |
| `last_used_at` | datetime \| null | | **Side-channel** | Aktivität. |
| `max_concurrent` | int | | Nein | Semaphore. |

---

## 10. Modul `providers` (Premium Provider Accounts)

### Collection `premium_provider_accounts`

Quelle: `backend/modules/providers/_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str (UUID) | | Nein | |
| `user_id` | str | Owner | Nein | |
| `provider_id` | str | xai / mistral / ollama_cloud / nano_gpt | **Side-channel** | Welche Premium-Provider. |
| `config` | dict | Plain | **Ja** | Falls non-secret-Felder vorhanden, oft user-spezifisch. |
| `config_encrypted` | dict[str, Fernet] | API-Keys | **Fernet (server)** | Auf User-DEK umstellen. |
| `last_test_status` | str \| null | | Side-channel | |
| `last_test_error` | str \| null | | **Ja** | Kann sensible Hinweise enthalten. |
| `last_test_at` | datetime \| null | | Side-channel | |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

---

## 11. Modul `integrations`

### Collection `user_integration_configs`

Quelle: `backend/modules/integrations/_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `user_id` | str | Owner | Nein | Composite-Key. |
| `integration_id` | str | xai_voice / lovense / … | **Side-channel** | Welche Integrationen. |
| `enabled` | bool | | **Side-channel** | |
| `config` | dict | Plain (z. B. `voice_id`) | **Ja** | User-Wahl. |
| `config_encrypted` | dict[str, Fernet] | Geheime Felder | **Fernet (server)** | Auf User-DEK umstellen. |

> Integrations-*Definitionen* (`IntegrationDefinition`) sind statisch im Code,
> nicht persistiert.

---

## 12. Modul `images`

### Collection `generated_images`

Quelle: `backend/modules/images/_models.py`, `_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` / `id` | str | | Nein | |
| `user_id` | str | Owner | Nein | |
| `blob_id` | str \| null | Storage-ID des Bildes | Nein | Routing. Blob selbst → siehe Blob-Abschnitt. |
| `thumb_blob_id` | str \| null | Thumbnail-Blob-ID | Nein | s. o. |
| `prompt` | str | Generations-Prompt | **Ja** | Content. |
| `model_id` | str | | **Side-channel** | |
| `group_id` | str | | **Side-channel** | |
| `connection_id` | str | FK | **Side-channel** | |
| `config_snapshot` | dict | Generation-Config (steps, sampler, …) | **Ja** | Kann Negative-Prompts u. ä. enthalten. |
| `width` / `height` | int \| null | | Side-channel | |
| `content_type` | str \| null | MIME | Side-channel | |
| `moderated` | bool | Upstream-Moderation gefiltert | **Side-channel** | Topic-Leak. |
| `moderation_reason` | str \| null | | **Ja** | Inhaltsleak. |
| `tags` | list[str] | "Phase II hook for E2EE-readiness" | **Ja** | Bereits im Code für E2EE markiert. |
| `generated_at` | datetime | | Side-channel | |

### Collection `user_image_configs`

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` / `id` | str (composite) | `{user_id}:{conn_id}:{group_id}` | Nein | |
| `user_id` | str | Owner | Nein | |
| `connection_id` | str | FK | Side-channel | |
| `group_id` | str | | Side-channel | |
| `config` | dict | User-spezifische Image-Gen-Config | **Ja** | Default-Negative-Prompts, Style-Choices. |
| `selected` | bool | Aktive Config | Nein | Server-Logik. |
| `updated_at` | datetime | | Side-channel | |

---

## 13. Modul `artefact`

### Collection `artefacts`

Quelle: `backend/modules/artefact/_models.py`, `_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | ObjectId | | Nein | |
| `session_id` | str | FK | Nein | |
| `user_id` | str | Owner | Nein | |
| `handle` | str | Artefakt-Handle (im Chat referenziert) | **Ja** | Vom LLM/User benannt. |
| `title` | str | | **Ja** | Content. |
| `type` | enum | markdown / code / html / svg / jsx / mermaid | **Side-channel** | Topic-Hint. |
| `language` | str \| null | Programmiersprache | **Side-channel** | Topic-Hint. |
| `content` | str | Volltext | **Ja** | Kerncontent. |
| `size_bytes` | int | | Side-channel | |
| `version` | int | | Nein | Versionierung. |
| `max_version` | int | | Nein | |
| `created_at` | datetime | | Side-channel | |
| `updated_at` | datetime | | Side-channel | |

### Collection `artefact_versions`

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | ObjectId | | Nein | |
| `artefact_id` | str | FK | Nein | |
| `version` | int | | Nein | |
| `content` | str | | **Ja** | Content. |
| `title` | str | | **Ja** | Content. |
| `created_at` | datetime | | Side-channel | |

---

## 14. Modul `settings`

### Collection `app_settings`

Quelle: `backend/modules/settings/_models.py`, `_repository.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` (`key`) | str | Setting-Key | Nein | Globale App-Settings. |
| `value` | str | | Nein | Server-globale Konfiguration, kein User-Content. |
| `updated_at` | datetime | | Nein | |
| `updated_by` | str | Admin-User-ID | Nein | Audit. |

> Globale App-Settings, kein User-Content. **E2EE-irrelevant.**

---

## 15. Modul `jobs`

### Redis-Streams (nicht MongoDB)

Quelle: `backend/jobs/_models.py`. `JobEntry` wird in Redis-Streams persistiert.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `id` | str | Job-ID | Nein | |
| `job_type` | enum | title_generation / memory_extraction / memory_consolidation | **Side-channel** | Welcher Job-Typ läuft. |
| `user_id` | str | Owner | Nein | |
| `model_unique_id` | str | | Side-channel | |
| `payload` | dict | Job-Payload | **Ja** | Kann Klartext-Content (für Memory-Extraction sogar Messages) enthalten. |
| `correlation_id` | str | | Nein | Tracing. |
| `created_at` | datetime | | Side-channel | |
| `attempt` | int | | Nein | |
| `execution_token` | str | Idempotenz-Key | Nein | |

> **Knackpunkt:** `payload` kann sehr sensibel sein (z. B. Konversations-Snippets
> für Memory-Extraction). Wenn das Backend den User-DEK nicht kennt
> (E2EE-Vollausbau), kann der Server den Inhalt nicht entpacken — die
> entsprechenden Jobs müssten clientseitig laufen.

---

## 16. Interne Collection `_migrations`

Quelle: `backend/modules/llm/_migration_connections_refactor.py`.

| Property | Typ | Bedeutung | Encrypt? | Begründung |
|---|---|---|---|---|
| `_id` | str | Migration-Marker | Nein | Server-Bootstrap. |

E2EE-irrelevant.

---

## 17. Blobs außerhalb MongoDB

| Quelle | Inhalt | Encrypt? | Hinweis |
|---|---|---|---|
| `storage_files.file_path` → Volume | Hochgeladene Dateien | **Ja** | Heute Klartext im Volume. Für E2EE: Client muss vor Upload mit User-DEK verschlüsseln. |
| `generated_images.blob_id` → Image-Storage | PNG/WebP-Blobs | **Ja** | Same. Thumbnail (`thumb_blob_id`) ebenso. |

> Blob-Verschlüsselung läuft *außerhalb* MongoDB — DEK-Wrap auf Blob-Ebene
> (z. B. AES-GCM-Stream mit IV im Header).

---

## 18. Redis-State (transient, aber persistiert)

Nicht aus den Models direkt sichtbar, aber laut CLAUDE.md vorhanden:

| Quelle | Inhalt | Encrypt? | Hinweis |
|---|---|---|---|
| Session-Cache (auth) | JWT-Refresh-Tokens (httpOnly) | Nein | Server-Auth. |
| Redis-Streams `events:*` | Events pro User-Session | **Ja** | Events tragen DTOs mit User-Content (`MessageDeltaEvent` z. B.). 24 h TTL. Catchup nach Reconnect. |
| Redis-Streams `jobs:*` | JobEntries (siehe Modul `jobs`) | siehe oben | |
| `llm:models:{conn_id}` Cache | Modell-Listen vom Provider | **Side-channel** | Welche Modelle ein User-Connection sieht. |
| `llm:models:premium:{user_id}:{provider_id}` | dito Premium | Side-channel | |

> **Architektur-Frage für Schritt 3:** Werden Events im Redis-Stream serverseitig
> nur weitergereicht (dann genügt Transport-Sicherheit + Client-seitige
> Entschlüsselung der Payloads), oder muss der Server Inhalte für
> Server-Logik lesen können? Heute liest der Server Inhalte sehr wohl
> (Memory-Extraction, Title-Gen, Vision-Description-Cache, …).

---

## 19. Side-Channel-Übersicht (für den Reviewer)

Sammlung aller Properties / Mechanismen, die auch bei verschlüsseltem Content
weiterhin Information leaken. Hier liegt der Reviewer-Fokus.

### 19.1 Indizes & Server-Operationen, die mit E2EE inkompatibel sind

| Index / Operation | Wo | Konflikt |
|---|---|---|
| `chat_messages.content_text` (Volltext) | `chat/_repository.py:29-33` | Server-Suche auf Klartext-Content. Mit E2EE entfällt Server-Volltextsuche. |
| `chat_sessions.title` Regex-Suche | `chat/_repository.py:131-139` | Wie oben für Session-Titel. |
| `knowledge_chunks` Vector-Search-Index (`$vectorSearch`) | `knowledge/_repository.py:44-62` | Embeddings müssen serverlesbar sein, sonst keine Server-Vector-Search. |
| `chat_messages.user_id_correlation_id` (sparse) | `chat/_repository.py:36-40` | Kein Konflikt — `correlation_id` muss server-lesbar sein (Retract-Flow). |
| Aggregate `get_quota_used` (Sum von `size_bytes`) | `storage/_repository.py:85-93` | Quota auf Größe — `size_bytes` muss klar sein, leakt aber Größe. |
| `memory.get_committed_entry_counts` Aggregate über state | `memory/_repository.py:192-213` | `state` muss klar sein. |

### 19.2 Größen-Leaks

Folgende Properties leaken Inhaltsgröße (auch bei verschlüsseltem Inhalt eindeutig):

- `chat_messages.token_count`, `chat_messages.usage`
- `chat_sessions.context_used_tokens`, `context_max_tokens`, `context_fill_percentage`, `context_status`
- `knowledge_documents.size_bytes`, `chunk_count`
- `knowledge_chunks.token_count`
- `memory_bodies.token_count`, `entries_processed`
- `storage_files.size_bytes`
- `artefacts.size_bytes`, `version`, `max_version`

**Reviewer-Frage:** Akzeptieren wir Größen-Leak (Standard bei den meisten E2EE-Systemen)
oder padden wir auf Bucket-Größen?

### 19.3 Beziehungs-/Topic-Leaks via Foreign Keys

- `persona_id`, `session_id`, `library_id`, `document_id`, `connection_id`, `model_unique_id` —
  Aggregation: "User X benutzt 80 % der Zeit Persona Y mit Modell Z" ist
  ohne User-Content rekonstruierbar.
- `knowledge_library_ids` (in personas und sessions) — welche Wissensgebiete pro
  Persona / Session.
- `attachment_ids`, `attachment_refs.file_id`, `image_refs.id` — welche
  Files/Bilder einer Nachricht beigelegt sind.

**Frage:** Müssen FKs blind/anonymisiert werden, oder ist der Performance-Preis zu hoch?

### 19.4 Topic-/Inhalts-Hints in scheinbar harmlosen Flags

- `nsfw` (personas, projects, knowledge_libraries) — explizit Topic-Klassifizierung.
- `category` (memory_journal_entries) — Topic-Klassifizierung.
- `role` (chat_messages) — Verteilung leakt Verlauf.
- `status` / `state` / `embedding_status` — Workflow-Verlauf.
- `moderated` / `moderation_reason` (generated_images) — was wurde geblockt.
- `refusal_text` (chat_messages) — was wurde abgelehnt.
- `media_type` / `content_type` / `type` (artefacts) / `language` (artefacts) — Dateitypen.
- `adapter_type` / `provider_id` / `integration_id` — welche Backends/Integrationen.
- `tools_enabled`, `auto_read`, `is_correction`, `auto_committed` — Feature-Nutzung.

### 19.5 Timing-Leaks

Jedes `created_at`, `updated_at`, `last_test_at`, `last_seen_at`, `last_used_at`,
`generated_at`, `committed_at`, `revoked_at`, `used_at`, `expires_at`, `extracted_at`,
`deleted_at`. Aktivitätsmuster über User sehr leicht ableitbar.

### 19.6 Auto-generierte Titel (Sonderfall)

`chat_sessions.title` wird durch ein **LLM** aus dem Konversationsinhalt erzeugt.
Das ist effektiv eine *Zusammenfassung* der Konversation — höchst sensibel.
Muss in jedem Fall **Ja**. Mit E2EE muss Title-Generation clientseitig laufen
oder auf statische Titel (z. B. erste 50 Zeichen, lokal generiert) ausweichen.

### 19.7 Hash-Hints

`host_key_hint`, `api_key_hint` (4 letzte Zeichen) — minimal, aber Brute-Force-Hilfe
gegen sehr schwache Keys. Heute irrelevant (Token-Entropie 256 Bit), bei E2EE-Review
kurz erwähnen.

### 19.8 Version-Strings

`last_sidecar_version`, `password_hash_version`, `current_dek_version` — Software-Version
und KDF-Generation. Side-channel klein, aber für Targeting nutzbar.

### 19.9 Server-Fernet vs. User-DEK

Heute existiert bereits Verschlüsselung für API-Keys / OAuth-Tokens, aber mit dem
**Server-Master-Key** (`backend.config.settings.encryption_key`). Für echtes E2EE
muss der Wrap-Key auf User-DEK umgestellt werden, sonst ist das nicht E2EE
sondern serverseitige Verschlüsselung-at-Rest. Betroffen:

- `llm_connections.config_encrypted`
- `premium_provider_accounts.config_encrypted`
- `user_integration_configs.config_encrypted`

### 19.10 Server-Logik die heute Klartext braucht

Diese Funktionen lesen heute User-Content im Backend — wenn der Content E2EE
wird, **müssen** diese Funktionen umgebaut oder client-seitig werden:

- **Title-Generation** (Job: `title_generation`) — liest erste Messages.
- **Memory-Extraction** (Job: `memory_extraction`) — liest User-Messages, schreibt `journal_entries`.
- **Memory-Consolidation** (Job: `memory_consolidation`) — liest journal_entries, schreibt memory_bodies.
- **Vision-Description-Cache** (`storage_files.vision_descriptions`) — Server schickt Bild an Vision-Modell.
- **Embedding** (`knowledge_chunks.vector`) — Server berechnet Embeddings.
- **Knowledge RAG** (`vector_search`) — Server matched Embeddings.
- **Web-Search-Anreicherung** (`web_search_context`) — Server holt Suchergebnisse.

Das ist die größte Architektur-Frage für Schritt 3.

---

## Anhang: Was ist NICHT in dieser Datei

- **Pure DTOs** in `shared/dtos/` und `shared/events/` — sind Wire-Format, nicht
  persistiert. Per Definition werden DTOs aus Documents abgeleitet, daher implizit
  abgedeckt.
- **In-Memory-Registries** (Pull-Tasks, Embedding-Queue, Semaphores) — kein
  Persistenz-Footprint.
- **Statische Definitionen** (`IntegrationDefinition`, `PremiumProviderDefinition`,
  Adapter-Klassen) — Code, nicht DB.
- **Frontend localStorage / IndexedDB** — separat zu betrachten, gehört nicht zu
  dieser Backend-Persistenz-Analyse.
