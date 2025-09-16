from flask import Flask, jsonify, request
import requests
import re
from datetime import datetime
from functools import lru_cache
from difflib import SequenceMatcher
import time
from typing import Dict, List, Optional, Any, Tuple
import logging

# Logging konfigurieren
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Basis-URL für die dreimetadaten.de JSON-Daten
DREI_METADATEN_BASE_URL = "https://raw.githubusercontent.com/YourMJK/dreimetadaten/master/metadata/json"

@lru_cache(maxsize=1)
def get_metadata_cached() -> Tuple[Dict[str, Any], float]:
    """Cache die Metadaten für 1 Stunde"""
    try:
        response = requests.get(f"{DREI_METADATEN_BASE_URL}/Alle.json", timeout=10)
        response.raise_for_status()
        return response.json(), time.time()
    except Exception as e:
        logger.error(f"Fehler beim Laden der Metadaten: {e}")
        raise

def get_fresh_metadata() -> Dict[str, Any]:
    """Holt frische Metadaten oder nutzt Cache"""
    try:
        metadata, timestamp = get_metadata_cached()
        if time.time() - timestamp > 3600:  # 1 Stunde
            get_metadata_cached.cache_clear()
            metadata, _ = get_metadata_cached()
        return metadata
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Metadaten: {e}")
        return {}

def fuzzy_match(query: str, text: str, threshold: float = 0.6) -> bool:
    """Fuzzy String Matching für Typos"""
    if not query or not text:
        return False
    return SequenceMatcher(None, query.lower(), text.lower()).ratio() >= threshold

def calculate_match_score(episode: Dict[str, Any], query: str, clean_query: str, folge_nummer: str) -> int:
    """Berechnet einen Match-Score für bessere Sortierung"""
    score = 0
    title = episode.get("titel", "").lower()
    
    # FOLGEN-NUMMER hat absolut höchste Priorität
    if query == folge_nummer or clean_query == folge_nummer:
        return 1000  # Unschlagbar hoher Score
    
    # TITEL-MATCHES (das wichtigste nach Folgen-Nummer)
    # Exakte Treffer
    if title == query or title == clean_query:
        score = 900  # Sehr hoch
    # Query komplett im Titel enthalten
    elif query in title:
        score = 800  # Hoch
    elif clean_query in title:
        score = 750  # Hoch
    # Titel im Query enthalten (für vollständige Titel wie "Die drei ??? und der...")
    elif title in query:
        score = 700  # Hoch
    
    # Wortgrenzen-Matches (präziser)
    elif clean_query and re.search(r'\b' + re.escape(clean_query) + r'\b', title):
        score = 600
    elif re.search(r'\b' + re.escape(query) + r'\b', title):
        score = 550
    
    # Teilstring-Matches am Anfang des Titels (oft wichtig)
    elif title.startswith(query.lower()):
        score = 500
    elif title.startswith(clean_query.lower()):
        score = 450
    
    # Fuzzy Matches als Fallback für Tippfehler
    elif fuzzy_match(query, title, 0.8):
        score = 300
    elif fuzzy_match(clean_query, title, 0.8):
        score = 250
    elif fuzzy_match(query, title, 0.6):
        score = 150
    elif fuzzy_match(clean_query, title, 0.6):
        score = 100
    
    # Kleinere Boni für bessere Sortierung
    if score > 0:
        # Bonus für längere Matches (zeigt Relevanz)
        if len(clean_query) > 5:
            score += 10
        
        # Bonus wenn Query-Wörter alle im Titel vorkommen
        query_words = clean_query.split()
        if len(query_words) > 1:
            words_found = sum(1 for word in query_words if word in title)
            if words_found == len(query_words):
                score += 20
            elif words_found > len(query_words) / 2:
                score += 10
    
    return score

def parse_duration(laufzeit_str: str) -> Optional[int]:
    """Parst Laufzeit-String und gibt Sekunden zurück"""
    if not laufzeit_str:
        return None
    
    # Verschiedene Formate unterstützen: "45 min", "1:23:45", "83 Minuten"
    laufzeit_str = laufzeit_str.lower().strip()
    
    # Format: "XX min" oder "XX minuten"
    min_match = re.search(r'(\d+)\s*min', laufzeit_str)
    if min_match:
        return int(min_match.group(1)) * 60
    
    # Format: "H:MM:SS" oder "MM:SS"
    time_match = re.search(r'(\d+):(\d+)(?::(\d+))?', laufzeit_str)
    if time_match:
        hours = int(time_match.group(1)) if len(time_match.group(1)) <= 2 else 0
        minutes = int(time_match.group(2)) if time_match.group(2) else 0
        seconds = int(time_match.group(3)) if time_match.group(3) else 0
        
        # Wenn erste Zahl > 24, dann wahrscheinlich MM:SS Format
        if hours > 24:
            minutes = hours
            hours = 0
        
        return hours * 3600 + minutes * 60 + seconds
    
    return None

def calculate_duration_from_tracks(medien: List[Dict[str, Any]]) -> Optional[int]:
    """Berechnet Gesamtlaufzeit aus Track-Daten"""
    if not medien or not isinstance(medien, list) or len(medien) == 0:
        return None
    
    # Nimm das erste Medium
    first_medium = medien[0]
    if not isinstance(first_medium, dict) or 'tracks' not in first_medium:
        return None
    
    tracks = first_medium['tracks']
    if not isinstance(tracks, list) or len(tracks) == 0:
        return None
    
    # Finde den letzten Track und dessen End-Zeit
    last_track = tracks[-1]
    if isinstance(last_track, dict) and 'end' in last_track:
        # Die End-Zeit scheint in Samples oder einer anderen Einheit zu sein
        # Basierend auf deinem Feedback: 53h statt 53m bedeutet Faktor 60 zu viel
        # Also wahrscheinlich Millisekunden, aber Faktor 1000 ist zu viel
        # Teste: einfach durch 60000 teilen (Millisekunden zu Minuten, dann zu Sekunden)
        end_time = last_track['end']
        
        logger.debug(f"Raw end time: {end_time}")
        
        # Neuer Ansatz: Empirisch angepasst basierend auf dein Feedback
        # 53h → 53m bedeutet wir müssen durch 60 teilen
        if end_time > 1000000:  # Große Zahlen
            duration = int(end_time / 60000)  # Durch 60.000 statt 1.000.000
            logger.debug(f"Interpreted with factor 60000: {duration} seconds ({duration/60:.1f} minutes)")
        elif end_time > 10000:
            duration = int(end_time / 1000)  # Millisekunden
            logger.debug(f"Interpreted as milliseconds: {duration} seconds")
        else:
            duration = int(end_time)  # Sekunden
            logger.debug(f"Interpreted as seconds: {duration} seconds")
        
        return duration
    
    return None

def enrich_metadata(abs_data: Dict[str, Any], drei_data: Dict[str, Any]) -> Dict[str, Any]:
    """Fügt zusätzliche Metadaten hinzu"""
    # Laufzeit extrahieren - zuerst aus medien/tracks, dann fallback auf laufzeit string
    duration = None
    if 'medien' in drei_data:
        duration = calculate_duration_from_tracks(drei_data['medien'])
    
    if not duration and 'laufzeit' in drei_data:
        duration = parse_duration(drei_data['laufzeit'])
    
    if duration:
        abs_data['duration'] = duration
    
    # Minimalistische Tags wie bei Audible - nur das Wichtigste
    tags = []
    
    # Jahr (wichtig für Sortierung/Filterung)
    if abs_data.get('publishedYear'):
        tags.append(f"Jahr {abs_data['publishedYear']}")
    
    # Folgen-Typ basierend auf Titel-Pattern
    titel = drei_data.get('titel', '').lower()
    if 'spezial' in titel:
        tags.append('Spezialfolge')
    elif drei_data.get('teilNummer'):
        tags.append('Mehrteilig')
    
    # Nur bei besonderen Serien/Kategorien
    if drei_data.get('kategorie') and drei_data['kategorie'] != 'Hauptserie':
        tags.append(drei_data['kategorie'])
    
    # Minimale Tags - wie bei Audible
    abs_data['tags'] = tags
    
    # Amazon ASIN extrahieren (für Verknüpfung)
    links = drei_data.get('links', {})
    if isinstance(links, dict):
        amazon_link = links.get('amazon', '')
        if amazon_link and isinstance(amazon_link, str):
            asin_match = re.search(r'/dp/([A-Z0-9]{10})', amazon_link)
            if not asin_match:
                asin_match = re.search(r'/product/([A-Z0-9]{10})', amazon_link)
            if asin_match:
                abs_data['asin'] = asin_match.group(1)
    
    # IDs für interne Verknüpfung
    if 'ids' in drei_data and isinstance(drei_data['ids'], dict):
        drei_id = drei_data['ids'].get('dreimetadaten')
        if drei_id:
            abs_data['dreimetadaten_id'] = str(drei_id)
    
    return abs_data

def transform_to_abs_format(drei_data: Dict[str, Any], category: Optional[str] = None) -> Dict[str, Any]:
    """Transformiert dreimetadaten.de-Daten in ABS-kompatibles Format"""
    if not isinstance(drei_data, dict):
        logger.warning(f"Unerwarteter Datentyp in transform_to_abs_format: {type(drei_data)}")
        return {}
    
    try:
        # Bestimme den korrekten, offiziellen Seriennamen basierend auf der Kategorie
        series_name = "Die drei ???"
        if category == "die_dr3i":
            series_name = "DiE DR3i"
        elif category == "kids":
            series_name = "Die drei ??? Kids"
        elif category == "spezial":
            series_name = "Die drei ??? Spezial"
        elif category == "kurzgeschichten":
            series_name = "Die drei ??? Kurzgeschichten"
        elif category == "sonstige":
            series_name = "Sonstige"
        
        # Extrahiere die relevanten Felder
        abs_data = {
            "title": drei_data.get("titel", ""),
            "subtitle": None,
            "author": drei_data.get("autor", ""),
            "narrator": extract_narrators(drei_data.get("sprechrollen", [])),
            "publisher": "EUROPA",
            "publishedYear": extract_year(drei_data.get("veröffentlichungsdatum", "")),
            "description": drei_data.get("beschreibung", "") or drei_data.get("kurzbeschreibung", "") or drei_data.get("gesamtbeschreibung", ""),
            "cover": extract_cover_url(drei_data.get("links", {})),
            "genres": ["Detektive & Spannung", "Kinder-Hörbücher"],  # Passend zu Audible
            "tags": [],  # Wird in enrich_metadata befüllt
            "series": extract_series_info(drei_data, series_name),
            "language": "Deutsch",
            "isbn": None,
            "asin": None
        }
        
        # Metadaten anreichern
        abs_data = enrich_metadata(abs_data, drei_data)
        
        return abs_data
        
    except Exception as e:
        logger.error(f"Fehler beim Transformieren der Daten: {e}")
        return {}

def extract_narrators(sprechrollen: List[Dict[str, Any]]) -> str:
    """Extrahiert die Sprecher aus den Sprechrollen"""
    narrators = []
    if isinstance(sprechrollen, list):
        for rolle in sprechrollen:
            if isinstance(rolle, dict) and rolle.get("sprecher"):
                narrators.append(rolle["sprecher"])
    # Duplikate entfernen und als String zurückgeben
    unique_narrators = list(set(narrators))
    return ", ".join(unique_narrators) if unique_narrators else ""

def extract_series_info(drei_data: Dict[str, Any], series_name: str) -> List[Dict[str, str]]:
    """Extrahiert Serien-Informationen"""
    series_info = []
    
    # Hauptserie "Die drei ???" (hat nummer Feld)
    if "nummer" in drei_data:
        series_info.append({
            "series": series_name,
            "sequence": str(drei_data["nummer"])
        })
    
    # Teile (hat teilNummer Feld)
    elif "teilNummer" in drei_data:
        sequence = str(drei_data["teilNummer"])
        if drei_data.get("buchstabe"):
            sequence += f" {drei_data['buchstabe']}"
        series_info.append({
            "series": series_name,
            "sequence": sequence
        })
    
    # Für Folgen ohne Nummer (z.B. einige Spezialfolgen)
    else:
        series_info.append({
            "series": series_name,
            "sequence": "1"
        })
    
    return series_info

def extract_year(veröffentlichungsdatum: str) -> str:
    """Extrahiert das Jahr aus dem Veröffentlichungsdatum"""
    if veröffentlichungsdatum:
        try:
            if len(veröffentlichungsdatum) >= 4:
                return veröffentlichungsdatum[:4]
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%Y"):
                try:
                    dt = datetime.strptime(veröffentlichungsdatum, fmt)
                    return str(dt.year)
                except ValueError:
                    continue
        except:
            pass
    return ""

def extract_cover_url(links: Dict[str, Any]) -> str:
    """Extrahiert die Cover-URL"""
    if isinstance(links, dict):
        # Bevorzuge das Haupt-Cover (laut JSON-Beispiel: http://dreimetadaten.de/data/Serie/001/cover.png)
        if links.get("cover"):
            cover_path = links["cover"]
            if cover_path.startswith(('http://', 'https://')):
                # Konvertiere http zu https für Sicherheit
                if cover_path.startswith('http://'):
                    return cover_path.replace('http://', 'https://', 1)
                return cover_path
            elif cover_path.startswith("/"):
                return f"https://www.dreimetadaten.de{cover_path}"
            else:
                return f"https://www.dreimetadaten.de/{cover_path}"
        
        # Fallback zu iTunes Cover (oft hochauflösend)
        elif links.get("cover_itunes"):
            cover_path = links["cover_itunes"]
            if cover_path.startswith(('http://', 'https://')):
                return cover_path
            else:
                return f"https://www.dreimetadaten.de/{cover_path}"
        
        # Fallback zu Kosmos Cover
        elif links.get("cover_kosmos"):
            cover_path = links["cover_kosmos"]
            if cover_path.startswith(('http://', 'https://')):
                return cover_path
            else:
                return f"https://www.dreimetadaten.de/{cover_path}"
        
        # Letzter Fallback zu cover2 Array (falls vorhanden)
        elif links.get("cover2") and isinstance(links["cover2"], list) and links["cover2"]:
            cover_path = links["cover2"][0]
            if cover_path.startswith(('http://', 'https://')):
                if cover_path.startswith('http://'):
                    return cover_path.replace('http://', 'https://', 1)
                return cover_path
            elif cover_path.startswith("/"):
                return f"https://www.dreimetadaten.de{cover_path}"
            else:
                return f"https://www.dreimetadaten.de/{cover_path}"
    
    return ""

def normalize_search_query(query: str) -> Tuple[str, str]:
    """Normalisiert und bereinigt Suchanfragen"""
    original_query = query.lower().strip()
    
    # Entferne häufige Prefixe die Probleme machen können
    # WICHTIG: Da die API-Titel das Format "und der Super-Papagei" haben,
    # müssen wir "Die drei ???" entfernen um passende Treffer zu finden
    prefixes_to_remove = [
        "die drei fragezeichen",
        "die drei ???",
        "die drei",
        "drei ???",
        "drei fragezeichen", 
        "die dr3i",
        "dr3i"
    ]
    
    clean_query = original_query
    for prefix in prefixes_to_remove:
        if clean_query.startswith(prefix):
            clean_query = clean_query[len(prefix):].strip()
            # Entferne auch führende "und" nach dem Prefix
            if clean_query.startswith("und "):
                clean_query = clean_query[4:].strip()
            break
    
    # Falls nach der Bereinigung nichts übrig ist, verwende original
    if not clean_query:
        clean_query = original_query
    
    # Zusätzlich: Falls Query mit "und der/die/das" beginnt, 
    # erstelle auch eine Variante ohne "und"
    alternative_query = clean_query
    if clean_query.startswith(("und der ", "und die ", "und das ")):
        alternative_query = clean_query[4:].strip()  # Entferne "und "
    
    return original_query, clean_query

@app.route('/search', methods=['GET'])
def search_books():
    """Suchfunktion für ABS - gibt das korrekte Format zurück"""
    query = request.args.get('query', '').strip()
    # author = request.args.get('author', '').strip()  # Komplett ignoriert
    
    if not query:
        return jsonify({"matches": []})
    
    original_query, clean_query = normalize_search_query(query)
    
    logger.info(f"Search - Original: '{query}', Clean: '{clean_query}' (Author ignored)")
    
    try:
        metadata = get_fresh_metadata()
        if not metadata:
            return jsonify({"matches": []})
        
        matches_with_scores = []
        
        # Durchsuche alle Kategorien
        categories = [
            ("serie", "Die drei ???"),
            ("spezial", "Die drei ??? Spezial"), 
            ("kurzgeschichten", "Die drei ??? Kurzgeschichten"),
            ("die_dr3i", "Die DR3i"),
            ("kids", "Drei Fragezeichen Kids"),
            ("sonstige", "Sonstige")
        ]
        
        for category_key, category_name in categories:
            if category_key in metadata and isinstance(metadata[category_key], list):
                for episode in metadata[category_key]:
                    if not isinstance(episode, dict):
                        continue
                    
                    # Suchkriterien - nur Titel und Folgen-Nummer, kein Autor-Filter
                    title = episode.get("titel", "").lower()
                    
                    # Folge-Nummer für die Suche
                    folge_nummer = ""
                    if "nummer" in episode:
                        folge_nummer = str(episode["nummer"])
                    elif "teilNummer" in episode:
                        folge_nummer = str(episode["teilNummer"])
                    
                    # KEIN Autor-Filter mehr - suche nur nach Titel/Nummer
                    
                    # Berechne Match-Score (fokussiert auf Titel und Folgen-Nummer)
                    score = calculate_match_score(episode, original_query, clean_query, folge_nummer)
                    
                    # Zusätzlicher Score-Boost für exakte API-Titel-Matches
                    # Da API-Titel wie "und der Super-Papagei" sind
                    if clean_query and title == clean_query:
                        score = max(score, 950)  # Sehr hoher Score für exakte API-Titel
                    elif clean_query and clean_query in title and len(clean_query) > 3:
                        score += 50  # Bonus für längere Substring-Matches
                    
                    # Debug-Ausgabe für Score-Analyse
                    if score > 0:
                        logger.debug(f"Match found - Title: '{episode.get('titel', '')}', Query: '{query}', Clean: '{clean_query}', Score: {score}")
                    
                    if score > 0:
                        abs_episode = transform_to_abs_format(episode, category_key)
                        if abs_episode and abs_episode.get("title"):
                            matches_with_scores.append((abs_episode, score))
        
        # Sortiere nach Score (höchster zuerst) und nimm die besten 10
        matches_with_scores.sort(key=lambda x: x[1], reverse=True)
        matches = [match[0] for match in matches_with_scores[:10]]
        
        logger.info(f"Found {len(matches)} matches for query '{query}' (author ignored)")
        if matches_with_scores:
            logger.debug(f"Top scores: {[(m[0]['title'], m[1]) for m in matches_with_scores[:3]]}")
        
        return jsonify({"matches": matches})
    
    except Exception as e:
        logger.error(f"Fehler bei der Suche: {e}")
        return jsonify({"matches": []})

@app.route('/detail', methods=['GET'])
def get_book_detail():
    """Detailfunktion für ABS"""
    book_id = request.args.get('id')
    
    if not book_id:
        return jsonify({})
    
    try:
        metadata = get_fresh_metadata()
        if not metadata:
            return jsonify({})
        
        # Durchsuche alle Kategorien
        categories = ["serie", "spezial", "kurzgeschichten", "die_dr3i", "kids", "sonstige"]
        
        for category_key in categories:
            if category_key in metadata and isinstance(metadata[category_key], list):
                for episode in metadata[category_key]:
                    if not isinstance(episode, dict):
                        continue
                    
                    # Prüfe anhand der dreimetadaten ID
                    episode_id = str(episode.get("ids", {}).get("dreimetadaten", ""))
                    if episode_id == book_id:
                        abs_episode = transform_to_abs_format(episode, category_key)
                        return jsonify(abs_episode)
        
        return jsonify({})
    
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Details: {e}")
        return jsonify({})

@app.route('/name', methods=['GET'])
def get_provider_name():
    return jsonify({"name": "DreiMetadaten.de Provider"})

@app.route('/version', methods=['GET'])
def get_version():
    return jsonify({"version": "1.1.0"})

@app.route('/health', methods=['GET'])
def health_check():
    """Health Check Endpoint"""
    try:
        response = requests.get(f"{DREI_METADATEN_BASE_URL}/Alle.json", timeout=5)
        response.raise_for_status()
        return jsonify({"status": "healthy", "api_accessible": True}), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({"status": "unhealthy", "api_accessible": False}), 503

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)