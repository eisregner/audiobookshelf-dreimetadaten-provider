# Audiobookshelf DreiMetadaten Provider

Ein spezialisierter Metadata-Provider für Audiobookshelf, der deutsche Hörspiele aus der [dreimetadaten.de](https://dreimetadaten.de) Datenbank durchsuchbar macht.

![Search](Images/Search.png "Search")

## Unterstützte Serien
- **Die drei ???** (Hauptserie)
- **Die drei ??? Kids** 
- **DiE DR3i**
- **Die drei ??? Spezial**
- **Die drei ??? Kurzgeschichten**

## Features
- **Intelligente Suche**: Findet Titel auch bei Teilangaben ("Super-Papagei" findet "und der Super-Papagei")
- **Präzise Metadaten**: Korrekte Laufzeiten, Sprecher, Cover und Beschreibungen
- **Saubere Tags**: Minimalistische Tags wie bei Audible
- **Folgen-Nummer Suche**: Direkte Suche nach Folgen-Nummer (z.B. "6")
- **Autor-unabhängig**: Suche funktioniert unabhängig von Autor-Angaben
- **Fuzzy Search**: Toleriert Tippfehler und findet ähnliche Titel

## Installation

### Dependencies installieren
```bash
pip install flask requests
```

### Provider starten
```bash
python abs_dreimetadata.py
```

Der Provider läuft dann auf `http://localhost:5000`

## Konfiguration in Audiobookshelf
![Config](Images/Config.png "Config")
1. Gehe zu **Einstellungen → Metadaten → Benutzerdefinierte Metadatenanbieter → Hinzufügen**
2. Füge einen neuen **Custom Metadata Provider** hinzu:
   - **Name**: DreiMetadaten Provider
   - **URL**: `http://localhost:5000` (oder deine Server-IP:5000)
3. Speichern und testen

## Beispiel-Suchen
```
"Die drei ??? und der Super-Papagei"  → Findet Folge 1
"Super-Papagei"                       → Findet Folge 1
"6"                                   → Findet Folge 6
"sprechende Totenkopf"               → Findet passende Folgen
"Eisenmann"                          → Findet "und der Eisenmann"
```

## Test

Nach dem Start einfach ein zweites Terminal öffnen um die Suche zu testen:

```bash
# Test-Suche
curl "http://localhost:5000/search?query=Super-Papagei"

# Health Check
curl "http://localhost:5000/health"
```

## Troubleshooting

### Provider wird nicht gefunden
- Stelle sicher dass der Provider auf Port 5000 läuft
- Prüfe die URL in Audiobookshelf (IP-Adresse verwenden statt localhost bei separaten Servern)
- Checke Firewall-Einstellungen

### Keine Suchergebnisse
- Teste mit einfachen Queries wie "1" oder "Papagei"
- Logs checken: Der Provider gibt Debug-Informationen in der Konsole aus

## Technische Details

- **Framework**: Flask
- **Datenquelle**: [dreimetadaten.de GitHub API](https://github.com/YourMJK/dreimetadaten)
- **Caching**: 1-Stunden Cache für API-Daten
- **Fuzzy Search**: Toleriert Tippfehler und Teilangaben
- **Score-basiertes Ranking**: Beste Treffer zuerst
- **Metadaten**: Cover, Laufzeit, Sprecher, Beschreibungen, ASIN

## API Endpoints

- `GET /search?query=<title>` - Suche nach Hörspielen
- `GET /detail?id=<id>` - Details zu einem spezifischen Hörspiel
- `GET /health` - Health Check
- `GET /name` - Provider Name
- `GET /version` - Version

## Credits

- Metadaten von [dreimetadaten.de](https://dreimetadaten.de) by [YourMJK](https://github.com/YourMJK)
- Für [Audiobookshelf](https://www.audiobookshelf.org) by [advplyr](https://github.com/advplyr)
