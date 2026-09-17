# Kundenarbeit in ERPNext: erster Umsetzungsschritt

Stand: 17.09.2026. Lokaler Entwicklungsvorschlag, nicht produktiv freigegeben.

## Entscheidung und Grenze

ERPNext bleibt vorerst die Arbeitsgrundlage für Kundenbetreuung, Leistungen,
Material und Abrechnung. Dafür sprechen vor allem die gemeinsamen Kunden-,
Artikel-, Lager-, Seriennummern- und Rechnungsdaten. Das vorhandene Frappe Wiki
bleibt die Dokumentationsablage. OpenProject wird in diesem Schritt nicht
wieder eingeführt.

Dies ist keine Aussage, dass ERPNext gleichwertigen Bedienkomfort für
Softwareentwicklung oder komplexe Projektplanung bietet. Der Maßstab ist der
eigene Serviceablauf: Anfrage bearbeiten, Leistung und Material erfassen,
Nachweis prüfen, Rechnung vorbereiten. Größere Eigenentwicklungen für eine
alternative Projektmanagementoberfläche sind nicht Teil dieses Schritts.

## Was dieser Stand ändert

- Die Kunden-Monatsübersicht zeigt gespeicherte Working-Time-Entwürfe sofort,
  einschließlich Datum, Dauer, Kundenbeschreibung und Vorgangsbezug.
- Erfasste Stunden setzen sich sichtbar aus bestätigten und noch nicht
  freigegebenen Stunden zusammen. Entwürfe erzeugen weder Umsatz noch
  abrechenbare Beträge und verändern bestehende Rechnungsnachweise nicht.
- Der Klick auf das Datum öffnet den zugehörigen Tag zur Prüfung.
- Lieferscheine des Monats erscheinen mit ihrem nativen Status und
  Abrechnungsprozentsatz. Entwürfe und Rücklieferungen erhalten keinen
  irreführenden Abrechnungsprozentsatz.
- „Materiallieferung erfassen“ öffnet einen nativen Lieferschein mit Kunde,
  Firma und Projekt. Menge, Lager und konkrete Seriennummer bleiben im
  ERPNext-Beleg. Es wird nichts automatisch gebucht.
- „Alle Lieferscheine“ führt zur Liste dieses Kundenprojekts über alle Monate,
  damit ältere Lieferungen bei der Abrechnung auffindbar bleiben.
- Datumsfilter für Tickets heißen ausdrücklich SLA-Frist. Persönliche
  Einsatzplanung ist damit noch nicht gelöst.

Die Übersichten respektieren die Rechte auf Projekt und Ursprungsbeleg.
Bei einem Tag mit mehreren Kunden erscheinen nur die Zeilen des geöffneten
Projekts. Interne Notizen werden nicht in die neue Übersicht übernommen.
Tabellen zeigen maximal acht Zeilen und kennzeichnen größere Mengen;
die Stunden-Summen berücksichtigen alle lesbaren passenden Zeilen.

## Arbeitsmodell

Ein dauerhafter Betreuungskontext pro Kunde bündelt laufende Arbeit.
Der Monat ist ein Filter, kein neu anzulegendes Projekt.
Abgegrenzte Vorhaben wie eine Servermigration benötigen weiterhin einen
eigenen Plan mit Aufgaben, Zuständigkeiten und Abschluss. Wie echte zusätzliche
Projekte mit Kundenkonto, Monatsübersicht und Portal zusammenspielen, ist noch
an einem konkreten Beispiel zu prüfen; keine historischen Projekte umhängen.

### Zeiten

Aktueller Ablauf: Projekt/Ticket/Aufgabe → „Zeit buchen“ → gespeicherter Entwurf
→ Tagesabschluss → native Timesheets → Billing Review → Rechnungsentwurf.

Dieser Änderungsschritt macht die gespeicherten Zeiten sichtbar, entfernt aber
noch nicht den verpflichtenden Tagesabschluss. Der vollständige Tag mit Beginn,
Ende, Pause und Zeitzuordnung ist für den beschriebenen Solo-Serviceablauf eine
unnötige Kopplung. Eine spätere Änderung muss Leistungserfassung und
Anwesenheit trennen, ohne zwei parallele Erfassungsquellen zu schaffen.

Vor einer solchen Änderung sind zu entscheiden und zu testen:

- Wie werden Dauerbuchungen ohne bekannte Uhrzeiten wahrheitsgemäß dargestellt?
  Der aktuelle Generator verteilt Dauern auf eine synthetische Tageszeitachse;
  diese darf nicht als nachgewiesene Einsatzchronologie ausgegeben werden.
- Wann werden Leistungszeilen geprüft und für die Abrechnung freigegeben?
- Wie funktionieren Nachträge, Korrekturen und bereits abgerechnete Zeiten?
- Wie bleiben bestehende Tagesdaten und spätere Mitarbeiterabläufe kompatibel?

Nicht denselben Einsatz zusätzlich manuell als Timesheet erfassen.

### Material und Seriennummern

Zielablauf mit vorhandenen ERPNext-Belegen, noch mit echten Stammdaten zu testen:

1. Wareneingang: Artikel, Menge, tatsächliche Hersteller-Seriennummer und Lager
   erfassen. Seriennummernpflicht muss passend zum Artikel eingerichtet sein.
2. Falls Fahrzeugbestände getrennt geführt werden sollen, das Fahrzeug als
   eigenes Lager abbilden und den Bestand mit Material Transfer dorthin bewegen.
   Das ist eine Organisationsentscheidung, keine automatische Einrichtung.
3. Beim Kunden die tatsächliche Lieferung im Lieferschein erfassen: Kunde,
   Projekt, Artikel, Menge, Quelllager und die konkret ausgelieferte Seriennummer.
   Bei vorhandenen Kundenaufträgen deren native Belegübernahme verwenden.
4. Den geprüften Lieferschein bestätigen. Ein Entwurf bewegt noch keinen Bestand.
5. Die Verkaufsrechnung aus dem Lieferschein vorbereiten und die nativen
   Lieferreferenzen erhalten. Keine zusätzliche Materialverbrauchsliste pflegen.
6. Rücknahme oder Austausch über die passenden nativen Rücklieferungsbelege
   prüfen; nicht lediglich die Notiz am Ticket ändern.

Ein Lieferschein deckt die Materialseite ab. Er ist nicht automatisch ein
vollständiges, unterschriebenes Aufmaß mit Tätigkeiten, Fotos oder Abnahme.
Ob dafür ein gemeinsamer Ausdruck aus bestehenden Belegen genügt, bleibt offen.
Auch der Rückweg von der Rechnung zur konkreten Seriennummer ist im Praxistest
zu prüfen. Dieser Schritt verändert weder Bestände noch Seriennummernstammdaten.

### Lizenzen

Einmalig verkaufte Lizenzen lassen sich über nicht lagergeführte Artikel im
Verkaufsablauf abbilden. Für feste wiederkehrende Entgelte kommt der bestehende
Subscription-Ablauf infrage. Verbrauchsabhängige Abrechnung, Laufzeitwechsel
und Lieferantenabgleich sind damit nicht automatisch erledigt.

Die kaufmännische Position ist von Bereitstellung und Verlängerung zu
unterscheiden. Für den ersten echten Lizenzfall müssen Kunde/Mandant,
Lizenzprodukt, Anzahl, Laufzeit und Lieferant nachvollziehbar zugeordnet werden.
Keine neue Lizenzdatenbank im Working-Time-Modul und keine Lizenzschlüssel in
kundensichtbare Zeitbeschreibungen aufnehmen.

### Dokumentation und Mitarbeiter

Ticket: Problem, Bearbeitungsstand und Kundenkommunikation.
Wiki: dauerhafte Konfiguration und wiederverwendbare Vorgehensweise.
Lieferschein: tatsächlich gelieferte Artikel und Seriennummern.
Zeitbuchung: geleistete Dauer und verständliche Leistungsbeschreibung.

Ein späterer Mitarbeiter braucht einen eigenen verknüpften Benutzer und
Mitarbeiterdatensatz sowie passende ERPNext-Rollen. Lesen, Erfassen und
Bestätigen von Lager- und Rechnungsbelegen sind getrennt zu prüfen. Die neuen
Verknüpfungen ersetzen keine Berechtigungen und gewähren keine zusätzlichen.

## Erprobung vor Produktivfreigabe

Ein kurzer Supportfall, ein Materialeinsatz und ein mehrstufiges Vorhaben:

1. Anfrage öffnen, beantworten und nächsten Schritt festlegen.
2. Zeit speichern: sofort im richtigen Kundenkonto sichtbar, noch kein
   freigegebener Abrechnungsbetrag.
3. Zweiter Kunde am selben Tag: keine fremden Beschreibungen oder Zeiten
   in der ersten Kundenansicht.
4. Tagesabschluss im bestehenden Ablauf: Entwurf verschwindet aus dem
   Entwurfsbereich, bestätigte Zeit erscheint genau einmal.
5. Material aus dem Fahrzeug mit echter Seriennummer liefern; die
   Seriennummer und offene Lieferung müssen wieder auffindbar sein.
6. Zeiten und Material zur Rechnung vorbereiten; prüfen, ob ein gemeinsamer
   Rechnungsentwurf im bestehenden Ablauf genügt. Keine automatische Vereinigung.
7. Nachtrag, Teilabrechnung und Rücklieferung prüfen; ältere offene Lieferungen
   über die Gesamtliste auffinden.
8. Mitarbeiterrolle: nur erlaubte eigene Zeiten und erlaubte Kunden-/Lagerbelege.

Die Docker-Integration und diese Bedienungstests sind Freigabevoraussetzungen.
Lokale Unit- und JavaScript-Prüfungen allein sind kein Produktivnachweis.

## Herstellerquellen

- [Lagerbewegungen](https://docs.frappe.io/erpnext/stock-entry)
- [Seriennummern und Chargen](https://docs.frappe.io/erpnext/serial-and-batch-bundle)
- [Lieferschein](https://docs.frappe.io/erpnext/delivery-note)
- [Abonnementpläne](https://docs.frappe.io/erpnext/subscription-plan)
- [Aufgaben und Vorhaben](https://docs.frappe.io/erpnext/tasks)
