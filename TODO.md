## Fehler

* ~~Modell ist an Chat gebunden:
man kann für einen existierenden Chat das Modell nicht wechseln~~ ERLEDIGT

## Missing features

* Man kann Memories nicht editieren
* Man sollte auf der Memories-Seite der Persona einen Button haben,
mit dem man triggern kann, dass Memories extrahiert werden

## Neue Features

* Ausgabe "time to first token" und "tokens per second" - sollte herleitbar sein aus dem stream?
* Während "model stil working"-Anzeige: Anzeige der vergangenen Zeit seit der letzten "transmission"
* Einführung Prometheus als eigenes Modul im Backend - es sollten folgende Daten anfangs in Prometheus sein:

  * Anzahl der Inferenzen als Counter und Typ (chat / job) per Model
  * Inferenzen per Model als Histogramm (Zeit)
  * Anzahl der abgebrochenen Inferenzen per Model
  * Anzahl der Tool Calls nach Model und Tool
  * Falls möglich: Histogramm über Dauer der Tool Calls nach Model und Tool
  * Anzahl der Modelle per Upstream Provider als Gauge
  * Anzahl der Embedding-Aufrufe, getrennt nach "Cached" und "Uncached"
