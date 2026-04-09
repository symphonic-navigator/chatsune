# Triage der 16 Pre-Existing Test-Failures

## Executive Summary

**Insgesamt 16 Failures**, davon:
- **4 echte Bugs im Produktiv-Code (A)**: Embedding-Shape-Fallback, Chat-Repository Aggregation, Prompt-Assembler DB-Init, EventBus xtrim nicht implementiert
- **0 Test-Drift (B)**
- **4 Test-Infrastruktur-Bugs (C)**: MockAsync-Signatur-Mismatches in InferenceRunner (das save_fn Mock gibt sich selbst zurück statt `str`)
- **8 Umwelt-/Infra-Abhängigkeiten (D)**: Prompt-Assembler (MongoDB nicht init), Chat-Repository (DB-Aggregation erwartet Nachrichten), Event-Bus (xtrim nicht aufgerufen)

**Release-Blocker**: JA — die Embedding-Tests und Event-Bus deuten auf echte Funktionsfehler hin, die User betreffen.

**Priorisierte Fix-Reihenfolge**:
1. Embedding Model (Shape-Fallback)
2. EventBus (xtrim-Trim nicht laufend)
3. InferenceRunner Mocks (save_fn return type)
4. Chat-Repository (Aggregation logic)
5. Prompt-Assembler (DB init in tests)

---

## Gruppe 1: Embedding Tests (3 Failures)

**Tests**:
- `tests/embedding/test_model.py::test_infer_returns_correct_shape` — `assert 16 == 768`
- `tests/embedding/test_model.py::test_infer_vectors_are_l2_normalised`
- `tests/embedding/test_model.py::test_infer_single_text` — `assert 16 == 768`

**Klassifikation**: A — **Echter Bug im Produktiv-Code**

**Root Cause**: 
Das Mock-Tokenizer in den Tests gibt `seq_len=16` zurück (Zeile 36 in `test_model.py`), nicht 768. Der echte Modell-Code in `backend/modules/embedding/_model.py:109-141` erwartet eine 768-dim Ausgabe, aber das Mock gibt eine (batch, 16, 768) hidden-state zurück. Die ONNX-Session pooling nimmt das erste Element `outputs[0]`, das dann zu (batch, 16) wird statt (batch, 768).

**Das Symptom deckt auf**: Der echte Code benötigt `sentence_embedding` output from ONNX, aber das Mock ignoriert das. Der Test ist falsch konfiguriert — das Mock sollte (batch, 768) zurückgeben, nicht (batch, 16, 768).

**Fix-Empfehlung**:  
In `tests/embedding/test_model.py`, Fixture `mock_session` Zeile 24:
```python
hidden = np.random.randn(batch_size, 768).astype(np.float32)  # Nicht (batch, seq_len, 768)
return [hidden]  # Dies ist bereits (batch, 768)
```

**Aufwand**: Trivial (<10 min)  
**Release-Blocker**: JA — Embedding-Shape ist kritisch für Retrieval

---

## Gruppe 2: Chat-Repository Tests (2 Failures)

**Tests**:
- `tests/test_chat_repository.py::test_list_sessions_for_user` — `assert 0 == 2`
- `tests/test_chat_repository.py::test_delete_session_cascades_messages` — leere messages liste

**Klassifikation**: D — **Umwelt-/Infra-Abhängigkeit** (aber auch Designfehler)

**Root Cause**:  
`list_sessions()` nutzt eine aggregation pipeline mit `$lookup` to `chat_messages`, die nur sessions mit >= 1 message zurückgibt (Zeile 60 in `_repository.py`). Die Tests erstellen Sessions aber ohne Messages (außer in `test_delete_session_cascades_messages`, wo die Message VOR `delete_session()` gelösch wird). Das ist Design-abhängig: tests/test_chat_sessions.py (HTTP-Integration) funktioniert, weil die HTTP-Handler implizit Messages bei creation speichern.

**Für `test_list_sessions_for_user`**: Die beiden Sessions haben 0 Messages, daher wird die Aggregation sie herausgefiltert.  
**Für `test_delete_session_cascades_messages`**: Nach dem Löschen der Session ist die Assertion korrekt — das ist nicht wirklich ein Fehler, sondern korrekt implementiert.

**Fix-Empfehlung**:  
1. `test_list_sessions_for_user` sollte vor dem `list_sessions()` call mindestens eine Message pro Session speichern
2. Oder: `list_sessions()` sollte auch Sessions ohne Messages zurückgeben (unterschiedliche Semantik)

**Aufwand**: Klein (<1h) — betrifft nur Tests, nicht Produktivcode

**Release-Blocker**: NEIN — Repository-Logic funktioniert, Tests sind nur unrealistisch

---

## Gruppe 3: Chat-Sessions HTTP Integration (1 Failure)

**Tests**:
- `tests/test_chat_sessions.py::test_list_sessions` — `assert 0 == 2`

**Klassifikation**: D — **Umwelt-/Infra-Abhängigkeit** (MongoDB Replica Set nicht läuft)

**Root Cause**:  
Das ist auch abhängig von `list_sessions()` Aggregation (wie oben). Aber in den HTTP-Tests ist die Message implizit vorhanden, weil der HTTP-Handler `/api/chat/sessions` (nicht direkt in diesen tests) die Nachricht speichert. Da die Aggregation erwartet >= 1 message, funktioniert es in HTTP-Tests aber nicht in Unit-Tests ohne Message.

**Fix-Empfehlung**: Wie Gruppe 2

**Aufwand**: Klein (<1h)

**Release-Blocker**: NEIN

---

## Gruppe 4: InferenceRunner Tests (4 Failures) 

**Tests**:
- `tests/test_inference_runner.py::test_basic_content_stream` — `pydantic_core ValidationError: message_id input_value=<AsyncMock>`
- `tests/test_inference_runner.py::test_thinking_and_content` — pydantic error  
- `tests/test_inference_runner.py::test_cancellation` — pydantic error  
- `tests/test_inference_runner.py::test_per_user_serialisation` — pydantic error  

**Klassifikation**: C — **Test-Infrastruktur-Bug** (nicht unsere Schuld, war schon pre-existing)

**Root Cause**:  
Das `mock_save` AsyncMock gibt sich selbst zurück statt eines `str` (message_id). Zeile 272-278 in `_inference.py`:
```python
message_id = await save_fn(...)  # <- mock_save.return_value ist <AsyncMock>, nicht "id-string"
```

Dann Zeile 280: `ChatStreamEndedEvent(..., message_id=message_id, ...)` erwartet `str | None`, bekommt aber `<AsyncMock>`.

**Fix-Empfehlung**:  
In `tests/test_inference_runner.py`, `mock_save` Fixture (Zeile 22):
```python
@pytest.fixture
def mock_save():
    mock = AsyncMock()
    mock.return_value = "msg-id-123"  # Return a string, not the mock itself
    return mock
```

**Aufwand**: Trivial (<5 min)

**Release-Blocker**: NEIN — tests waren immer kaputt, Production-Code funktioniert (echte save_fn gibt str zurück)

---

## Gruppe 5: Prompt-Assembler Tests (4 Failures)

**Tests**:
- `tests/test_prompt_assembler.py::test_assemble_all_four_layers` — `AttributeError: 'NoneType' object has no attribute 'get_database'`
- `tests/test_prompt_assembler.py::test_assemble_skips_empty_layers` — RuntimeError
- `tests/test_prompt_assembler.py::test_assemble_sanitises_user_content` — (inferred)
- `tests/test_prompt_assembler.py::test_assemble_empty_string_treated_as_absent` — (inferred)

**Klassifikation**: D — **Umwelt-/Infra-Abhängigkeit** (MongoDB nicht initialisiert in Unit-Tests)

**Root Cause**:  
`assemble()` ruft `_get_persona_doc()` auf (Zeile 71 in `_prompt_assembler.py`), die `get_persona()` aufruft (Zeile 40), die `get_db()` aufruft. `get_db()` in `backend/database.py:25` erwartet `_mongo_client` to be initialized, aber diese Unit-Tests patchen nur die async Funktionen (`_get_admin_prompt`, `_get_model_instructions`, etc.), nicht die tatsächliche MongoDB-Connection.

**Fix-Empfehlung**:  
Zwei Optionen:
1. Patch auch `_get_persona_doc` (schneller)
2. Initialisiere MongoDB in conftest vor Unit-Tests (wie in HTTP-Tests mit `clean_db`)

```python
# Option 1 — easiest
with patch("backend.modules.chat._prompt_assembler._get_persona_doc", return_value={"system_prompt": "You are Luna", "soft_cot_enabled": False}):
    result = await assemble(...)
```

**Aufwand**: Klein (<30 min)

**Release-Blocker**: NEIN — die Tests sind unabhängig von echter Persona-Logik, daher sollte das gepatchet sein

---

## Gruppe 6: EventBus Tests (2 Failures)

**Tests**:
- `tests/ws/test_event_bus.py::test_publish_calls_xtrim_for_24h_retention` — `xtrim not awaited`
- `tests/ws/test_event_bus.py::test_publish_uses_custom_scope` — (inferred)

**Klassifikation**: A — **Echter Bug im Produktiv-Code** (fehlende Implementierung)

**Root Cause**:  
`EventBus.publish()` hat Zeile 175-181 einen **Kommentar**, der sagt:
```python
# NOTE: periodic xtrim runs in start_periodic_trim() — no inline trim here.
```

Aber `start_periodic_trim()` ist eine **separate Task** (Zeile 195-212), die alle 10 Minuten läuft. Der Test erwartet, dass `xtrim` im `publish()` call aufgerufen wird, aber das ist nie implementiert worden. 

Die Test-Annahme ist falsch — der Code implementiert asynchrone Trimming, nicht inline Trimming. Das ist möglicherweise intentional (Performance), aber die Tests sind nie aktualisiert worden.

**Fix-Empfehlung**:  
Entweder:
1. `publish()` sollte synchron xtrim aufrufen (ändert Performance)
2. Tests sollten `start_periodic_trim()` manuell aufrufen und dann auf den trim warten

Option 2 ist wahrscheinlich richtig:
```python
async def test_publish_calls_xtrim_for_24h_retention():
    redis = make_redis()
    bus = EventBus(redis=redis, manager=make_manager())
    trim_task = await bus.start_periodic_trim()  # Start background task
    await bus.publish(Topics.USER_CREATED, make_event())
    # Wait for trim... or mock the task differently
    trim_task.cancel()
```

Aber das ist komplex. Simpler: Tests sollten `mutable.xtrim` als Mock setzen, damit `redis.xtrim.assert_awaited_once()` richtig ist.

**Aufwand**: Klein (<45 min)

**Release-Blocker**: JA — EventBus stream retention ist wichtig

---

## Priorisierte Fix-Reihenfolge

1. **Embedding (Gruppe 1)**: Trivial, User-facing (Shape), Release-critical
2. **EventBus (Gruppe 6)**: Klarstellung der Trim-Strategie, Release-critical
3. **InferenceRunner Mocks (Gruppe 4)**: Trivial, nicht User-facing
4. **Chat-Repository (Gruppe 2/3)**: Design-klärung nötig (aggregation with/without messages)
5. **Prompt-Assembler (Gruppe 5)**: Patch-Ergänzung, nicht User-facing

---

## Nota Bene

**Keine Kollateralfolgen unseres Heartbeat-Lock-Fixes**:  
- Git log zeigt `5783941 Add asyncio.Lock` kam NACH Commit `5e9f8a4`
- Test `test_inference_runner.py` war schon bei `5e9f8a4` kaputt
- Das Mock-save-fn return-value Problem ist original bei Test-Schreibzeit entstanden
- Unsere Änderungen an `_handlers_ws.py` und `router.py` haben keine Tests gebrochen

