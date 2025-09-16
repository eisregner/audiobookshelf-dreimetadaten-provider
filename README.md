# Audiobookshelf DreiMetadaten Provider

Ein spezialisierter Metadata-Provider für Audiobookshelf, der deutsche Hörspiele aus der [dreimetadaten.de](https://dreimetadaten.de) Datenbank durchsuchbar macht.

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

### Option 1: Docker (Empfohlen)
```bash
git clone https://github.com/eisregner/audiobookshelf-dreimetadaten-provider.git
cd audiobookshelf-dreimetadaten-provider
docker-compose up -d
```

### Option 2: Manuell
```bash
git clone https://github.com/eisregner/audiobookshelf-dreimetadaten-provider.git
cd audiobookshelf-dreimetadaten-provider
pip install -r requirements.txt
python abs_dreimetadata.py
```

Der Provider läuft dann auf `http://localhost:5000`

## Konfiguration in Audiobookshelf

1. Gehe zu **Einstellungen → Metadaten → Benutzerdefinierte Metadatenanbieter → Hinzufügen**
2. Füge einen neuen **Custom Metadata Provider** hinzu:
   - **Name**: DreiMetadaten Provider
   - **URL**: `http://localhost:5000` (oder deine Server-IP:5000)
3. Speichern und testen

## API Endpoints

- `GET /search?query=<title>` - Suche nach Hörspielen
- `GET /detail?id=<id>` - Details zu einem spezifischen Hörspiel
- `GET /health` - Health Check
- `GET /name` - Provider Name
- `GET /version` - Version

## Beispiel-Suchen
```
"Die drei ??? und der Super-Papagei"  → Findet Folge 1
"Super-Papagei"                       → Findet Folge 1
"6"                                   → Findet Folge 6
"sprechende Totenkopf"               → Findet passende Folgen
"Eisenmann"                          → Findet "und der Eisenmann"
```

## Dateien im Repository

### Hauptdateien
- `abs_dreimetadata.py` - Der Flask-Provider (Hauptdatei)
- `requirements.txt` - Python-Dependencies
- `Dockerfile` - Für Docker-Build
- `docker-compose.yml` - Einfaches Docker-Setup

### requirements.txt
```
flask==2.3.3
requests==2.31.0
```

### Dockerfile
```dockerfile
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY abs_dreimetadata.py .

EXPOSE 5000

CMD ["python", "abs_dreimetadata.py"]
```

### docker-compose.yml
```yaml
version: '3.8'

services:
  dreimetadaten-provider:
    build: .
    ports:
      - "5000:5000"
    restart: unless-stopped
```

## Lokaler Test

Nach der Installation kannst du testen:

```bash
# Provider starten
python abs_dreimetadata.py

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
- Provider läuft und ist erreichbar
- Teste mit einfachen Queries wie "1" oder "Papagei"
- Logs checken: Der Provider gibt Debug-Informationen in der Konsole aus

### Docker-Probleme
```bash
# Logs anschauen
docker-compose logs

# Container neu starten
docker-compose restart

# Clean rebuild
docker-compose down
docker-compose up --build
```

## Technische Details

- **Framework**: Flask
- **Datenquelle**: [dreimetadaten.de GitHub API](https://github.com/YourMJK/dreimetadaten)
- **Caching**: 1-Stunden Cache für API-Daten
- **Fuzzy Search**: Toleriert Tippfehler und Teilangaben
- **Score-basiertes Ranking**: Beste Treffer zuerst
- **Metadaten**: Cover, Laufzeit, Sprecher, Beschreibungen, ASIN

## Entwicklung

### Lokale Entwicklung
```bash
git clone https://github.com/eisregner/audiobookshelf-dreimetadaten-provider.git
cd audiobookshelf-dreimetadaten-provider

# Dependencies installieren
pip install -r requirements.txt

# Debug-Modus starten
python abs_dreimetadata.py

# Der Provider läuft mit Debug-Logs auf http://localhost:5000
```

### Code-Struktur
- `get_fresh_metadata()` - Lädt und cached API-Daten
- `normalize_search_query()` - Bereinigt Suchanfragen
- `calculate_match_score()` - Bewertet Suchrelevanz
- `transform_to_abs_format()` - Konvertiert zu ABS-Format
- `enrich_metadata()` - Fügt zusätzliche Metadaten hinzu

## Contributing

Contributions sind willkommen! 

### Bug Reports
- Beschreibe das Problem
- Füge Log-Ausgaben hinzu
- Erwähne deine Audiobookshelf- und Provider-Version

### Feature Requests
- Beschreibe den gewünschten Feature
- Erkläre den Nutzen
- Beispiele sind hilfreich

### Pull Requests
1. Fork das Repository
2. Erstelle einen Feature Branch
3. Teste deine Änderungen
4. Öffne einen Pull Request mit Beschreibung

## Lizenz

MIT License - siehe [LICENSE](LICENSE) für Details.

## Credits

- Metadaten von [dreimetadaten.de](https://dreimetadaten.de) by [YourMJK](https://github.com/YourMJK)
- Für [Audiobookshelf](https://www.audiobookshelf.org) by [advplyr](https://github.com/advplyr)
- API-Dokumentation: [dreimetadaten GitHub](https://github.com/YourMJK/dreimetadaten)

## Changelog

### v1.0.0
- Initiale Version
- Unterstützung für alle Drei-Fragezeichen-Serien
- Intelligente Suche mit Fuzzy-Matching
- Docker-Support
- Caching und Performance-Optimierungen
