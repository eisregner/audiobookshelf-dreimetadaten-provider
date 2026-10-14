from flask import Flask, jsonify, request
import requests
import os
import re
import threading
import time
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Any, Tuple
import logging

# Logging konfigurieren
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

VERSION = "1.2.0"

# Komplette Metadaten aller Kategorien von dreimetadaten.de
METADATA_URL = os.environ.get(
    "METADATA_URL",
    "https://raw.githubusercontent.com/YourMJK/dreimetadaten/master/metadata/json/Alle.json",
)
# Wie lange die Daten gültig sind, bevor auf Änderungen geprüft wird (Sekunden)
CACHE_TTL = int(os.environ.get("CACHE_TTL", "3600"))
# Nach einem fehlgeschlagenen Abruf erst nach dieser Zeit erneut versuchen (Sekunden)
RETRY_AFTER = 60
# Optional: Schlüssel, den Audiobookshelf im AUTHORIZATION-Header mitschicken muss
API_KEY = os.environ.get("API_KEY", "")

MAX_RESULTS = 10
MIN_SCORE = 100

# Cover-Varianten: Name für COVER_PRIORITY → Feld in den Links von dreimetadaten.de
COVER_SOURCES = {
    "dreimetadaten": "cover",                     # 2048px PNG ohne EUROPA-Logo (nicht bei Kids)
    "artwork": "artwork",                         # nur die Illustration ohne Schrift (nicht bei Kids)
    "apple": "cover_itunes",                      # offizielles Cover mit Logo von Apple Music
    "dreifragezeichen": "cover_dreifragezeichen", # offizielles Cover mit Logo von dreifragezeichen.de
    "kosmos": "cover_kosmos",                     # Cover von Kosmos über web.archive.org (nur Hauptserie)
}
# Standard-Reihenfolge, gleichzeitig Ausweichlösung, wenn die gewünschte Variante fehlt
DEFAULT_COVER_PRIORITY = ["dreimetadaten", "apple", "dreifragezeichen", "kosmos"]

# Kategorie-Schlüssel aus der JSON → Serienname in Audiobookshelf
SERIES_NAMES = {
    "serie": "Die drei ???",
    "spezial": "Die drei ??? Spezial",
    "kurzgeschichten": "Die drei ??? Kurzgeschichten",
    "die_dr3i": "DiE DR3i",
    "kids": "Die drei ??? Kids",
    "sonstige": "Sonstige",
}

# Kategorien ohne Folgennummer, deren Reihenfolge in der JSON der offiziellen Position entspricht
POSITIONAL_CATEGORIES = {"spezial", "kurzgeschichten"}

# Wörter am Anfang einer Suche, die auf eine Kategorie hinweisen
CATEGORY_HINTS = {
    "kids": "kids",
    "dr3i": "die_dr3i",
    "spezial": "spezial",
    "kurzgeschichte": "kurzgeschichten",
    "kurzgeschichten": "kurzgeschichten",
}

# Präfixe, die vor dem eigentlichen Titel stehen können (z.B. aus Ordnernamen)
# und die Folgennummer, z.B. "Die drei ??? - Folge 006 - und der ..."
# Füllwörter, die beim Wortvergleich nicht zählen
STOPWORDS = {"und", "der", "die", "das", "des", "dem", "den", "ein", "eine", "im", "in", "am", "an", "auf",
             "von", "vom", "zum", "zur", "mit", "drei", "kids", "folge"}

QUERY_PREFIX_RE = re.compile(
    r"^(?:die drei fragezeichen|drei fragezeichen|die drei|ddf|die dr3i|dr3i|kids|spezial"
    r"|kurzgeschichten?|folge|nr|nummer|(\d{1,3}))(?:\s+|$)"
)


class MetadataStore:
    """Hält die Metadaten im Speicher und lädt sie nur bei Änderungen neu.

    Schlägt ein Abruf fehl, werden die zuletzt geladenen Daten weiter verwendet.
    """

    def __init__(self, url: str, ttl: int):
        self.url = url
        self.ttl = ttl
        self.lock = threading.Lock()
        self.data: Optional[Dict[str, Any]] = None
        self.entries: List[Dict[str, Any]] = []
        self.by_id: Dict[str, Dict[str, Any]] = {}
        self.etag: Optional[str] = None
        self.checked_at = 0.0
        self.loaded_at = 0.0
        self.last_error: Optional[str] = None

    def get(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            if self.data is None or time.time() - self.checked_at >= self.ttl:
                try:
                    self._refresh()
                    self.last_error = None
                except Exception as e:
                    self.last_error = str(e)
                    logger.error(f"Fehler beim Laden der Metadaten: {e}")
                    # Nicht bei jeder Anfrage erneut versuchen
                    self.checked_at = time.time() - self.ttl + RETRY_AFTER
            return self.data

    def _refresh(self) -> None:
        headers = {"If-None-Match": self.etag} if self.etag and self.data is not None else {}
        response = requests.get(self.url, headers=headers, timeout=30)
        self.checked_at = time.time()
        if response.status_code == 304:
            logger.debug("Metadaten unverändert")
            return
        response.raise_for_status()
        data = response.json()
        self.entries, self.by_id = build_index(data)
        self.data = data
        self.etag = response.headers.get("ETag")
        self.loaded_at = self.checked_at
        logger.info(f"Metadaten geladen: {len(self.entries)} Hörspiele, Version {data.get('dbInfo', {}).get('version', '?')}")


store = MetadataStore(METADATA_URL, CACHE_TTL)


def normalize(text: str) -> str:
    """Kleinschreibung, Satzzeichen entfernen, Leerzeichen zusammenfassen"""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def strip_und(title: str) -> str:
    """Entfernt das typische "und der/die/das" am Titelanfang"""
    return re.sub(r"^und (?:der |die |das )?", "", title)


def build_index(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Bereitet alle Hörspiele einmalig für die Suche auf"""
    entries = []
    by_id = {}
    for category in SERIES_NAMES:
        episodes = data.get(category)
        if not isinstance(episodes, list):
            continue
        for position, episode in enumerate(episodes, start=1):
            if not isinstance(episode, dict) or not episode.get("titel"):
                continue
            if "nummer" in episode:
                sequence = str(episode["nummer"])
            elif category in POSITIONAL_CATEGORIES:
                sequence = str(position)
            else:
                sequence = None
            title = normalize(episode["titel"])
            entry = {
                "category": category,
                "episode": episode,
                "sequence": sequence,
                "title": title,
                "short_title": strip_und(title),
            }
            entries.append(entry)
            drei_id = episode.get("ids", {}).get("dreimetadaten")
            if drei_id is not None:
                by_id[str(drei_id)] = entry
    return entries, by_id


def parse_query(query: str) -> Tuple[str, str, Optional[int], Optional[str]]:
    """Zerlegt eine Suche in Titel, Folgennummer und Kategorie-Hinweis

    Gibt (komplette Suche, Titel ohne Präfixe, Folgennummer, Kategorie) zurück.
    """
    full = normalize(query)
    rest = full
    number = None
    category = None
    while True:
        match = QUERY_PREFIX_RE.match(rest)
        if not match or not match.group(0):
            break
        word = match.group(0).strip()
        if match.group(1) is not None:
            if number is not None:
                break
            number = int(match.group(1))
        elif word.split()[-1] in CATEGORY_HINTS:
            category = CATEGORY_HINTS[word.split()[-1]]
        rest = rest[match.end():]
    return full, rest, number, category


def title_score(query: str, title: str, short_title: str) -> float:
    """Bewertet, wie gut eine Suche zu einem Titel passt (0 = kein Treffer)"""
    if not query:
        return 0
    if query in (title, short_title):
        score = 900
    elif f" {query} " in f" {title} ":
        score = 800
    elif query in title:
        score = 700
    elif len(short_title) > 3 and f" {short_title} " in f" {query} ":
        # Suche enthält den kompletten Titel plus weitere Wörter
        score = 650
    else:
        # Ohne "und der ..." vergleichen, sonst wirkt jeder Titel mit gleichem Anfang ähnlich
        ratio = SequenceMatcher(None, strip_und(query), short_title).ratio()
        if ratio >= 0.8:
            score = 300
        elif ratio >= 0.6:
            score = 150
        else:
            # Anteil der Suchwörter, die im Titel vorkommen
            words = [w for w in query.split() if len(w) > 2 and w not in STOPWORDS]
            title_words = set(title.split())
            found = sum(1 for w in words if w in title_words)
            if not words or found / len(words) < 0.5:
                return 0
            score = 100 + 100 * found / len(words)
    # Ähnlichkeit als Feinsortierung bei gleicher Stufe (z.B. kürzerer Titel vor längerem)
    return score + 10 * SequenceMatcher(None, query, short_title).ratio()


def match_score(entry: Dict[str, Any], full: str, rest: str, number: Optional[int], category: Optional[str]) -> float:
    """Gesamtbewertung eines Hörspiels für eine Suche"""
    if number is not None and not rest:
        # Nur Präfix + Nummer (z.B. "Folge 6"): kein Titelvergleich
        score = 0
    else:
        score = max(title_score(full, entry["title"], entry["short_title"]),
                    title_score(rest, entry["title"], entry["short_title"]))

    if number is not None and entry["episode"].get("nummer") == number:
        # Nur eine Nummer gesucht → eindeutig; sonst Bonus, der einen exakten Titel nicht schlägt
        score += 1000 if not rest else 300

    if score > 0:
        if category and entry["category"] == category:
            score += 150
        elif not category and entry["category"] == "serie":
            score += 5  # Bei Gleichstand die Hauptserie bevorzugen
    return score


def duration_minutes(episode: Dict[str, Any]) -> Optional[int]:
    """Gesamtlaufzeit in Minuten (so erwartet es Audiobookshelf)"""
    total_ms = episode.get("gesamtdauer")
    if not total_ms:
        # Fallback: Ende des letzten Tracks jedes Mediums aufsummieren
        total_ms = 0
        for medium in episode.get("medien") or []:
            tracks = medium.get("tracks") if isinstance(medium, dict) else None
            if tracks and isinstance(tracks[-1], dict):
                total_ms += tracks[-1].get("end", 0)
    if not total_ms:
        return None
    return round(total_ms / 60000)


def extract_narrators(sprechrollen: List[Dict[str, Any]]) -> str:
    """Sprecher in der Reihenfolge der Rollen (Hauptsprecher zuerst), ohne Duplikate"""
    narrators = []
    if isinstance(sprechrollen, list):
        for rolle in sprechrollen:
            if not isinstance(rolle, dict) or not rolle.get("sprecher"):
                continue
            # Mehrere Sprecher einer Rolle sind mit Komma getrennt
            for name in rolle["sprecher"].split(","):
                name = name.strip()
                if name and name not in narrators:
                    narrators.append(name)
    return ", ".join(narrators)


def extract_year(veröffentlichungsdatum: str) -> str:
    """Extrahiert das Jahr aus dem Veröffentlichungsdatum (Format YYYY-MM-DD)"""
    match = re.match(r"\d{4}", veröffentlichungsdatum or "")
    return match.group(0) if match else ""


def absolute_url(path: str) -> str:
    """Macht relative Pfade absolut und erzwingt https"""
    if path.startswith("http://"):
        return "https://" + path[len("http://"):]
    if path.startswith("https://"):
        return path
    return "https://dreimetadaten.de/" + path.lstrip("/")


def parse_cover_priority(value: str) -> List[str]:
    """Liest die gewünschte Cover-Reihenfolge, z.B. "apple,dreimetadaten"

    Nicht genannte Varianten werden als Ausweichlösung angehängt, damit es immer ein Cover gibt.
    """
    priority = []
    for name in (n.strip().lower() for n in value.split(",")):
        if not name:
            continue
        if name not in COVER_SOURCES:
            logger.warning(f"Unbekannte Cover-Variante '{name}' in COVER_PRIORITY ignoriert "
                           f"(möglich: {', '.join(COVER_SOURCES)})")
        elif name not in priority:
            priority.append(name)
    return priority + [n for n in DEFAULT_COVER_PRIORITY if n not in priority]


COVER_PRIORITY = parse_cover_priority(os.environ.get("COVER_PRIORITY", ""))


def extract_cover_url(links: Dict[str, Any]) -> str:
    """Cover-URL in der Reihenfolge von COVER_PRIORITY, sonst Alternativen"""
    if not isinstance(links, dict):
        return ""
    for name in COVER_PRIORITY:
        key = COVER_SOURCES[name]
        if isinstance(links.get(key), str) and links[key]:
            return absolute_url(links[key])
    cover2 = links.get("cover2")
    if isinstance(cover2, list) and cover2 and isinstance(cover2[0], str):
        return absolute_url(cover2[0])
    return ""


def transform_to_abs_format(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Wandelt ein Hörspiel in das BookMetadata-Format von Audiobookshelf um"""
    episode = entry["episode"]
    category = entry["category"]

    series = {"series": SERIES_NAMES[category]}
    if entry["sequence"]:
        series["sequence"] = entry["sequence"]

    year = extract_year(episode.get("veröffentlichungsdatum", ""))

    # Minimalistische Tags wie bei Audible
    tags = []
    if year:
        tags.append(f"Jahr {year}")
    if category == "spezial":
        tags.append("Spezialfolge")
    if episode.get("teile"):
        tags.append("Mehrteilig")

    abs_data = {
        "title": episode.get("titel", ""),
        "author": episode.get("autor", ""),
        "narrator": extract_narrators(episode.get("sprechrollen", [])),
        "publisher": "EUROPA",
        "publishedYear": year,
        "description": episode.get("beschreibung") or episode.get("kurzbeschreibung") or episode.get("gesamtbeschreibung") or "",
        "cover": extract_cover_url(episode.get("links", {})),
        "genres": ["Detektive & Spannung", "Kinder-Hörbücher"],  # Passend zu Audible
        "tags": tags,
        "series": [series],
        "language": "Deutsch",
    }
    # Keine ASIN: dreimetadaten.de kennt nur die Amazon-ID der CD, nicht die Audible-ASIN

    duration = duration_minutes(episode)
    if duration:
        abs_data["duration"] = duration

    return abs_data


@app.before_request
def check_api_key():
    """Prüft den optionalen API-Schlüssel (in Audiobookshelf als "Authorization Header Value")"""
    if API_KEY and request.endpoint == "search_books" and request.headers.get("Authorization") != API_KEY:
        return jsonify({"error": "Unauthorized"}), 401


@app.route('/search', methods=['GET'])
def search_books():
    """Suchfunktion für ABS - gibt das korrekte Format zurück"""
    query = request.args.get('query', '').strip()
    # Der Autor wird ignoriert: Dateien sind oft mit Sprechern oder "Die drei ???" als Autor getaggt

    if not query:
        return jsonify({"matches": []})

    full, rest, number, category = parse_query(query)
    logger.info(f"Suche: '{query}' → Titel: '{rest}', Nummer: {number}, Kategorie: {category}")

    if store.get() is None:
        return jsonify({"error": "Metadaten nicht verfügbar"}), 500

    scored = []
    for entry in store.entries:
        score = match_score(entry, full, rest, number, category)
        if score >= MIN_SCORE:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)

    for score, entry in scored[:3]:
        logger.debug(f"  {score:7.1f}  {SERIES_NAMES[entry['category']]} {entry['sequence'] or '-'}: {entry['episode']['titel']}")

    matches = [transform_to_abs_format(entry) for _, entry in scored[:MAX_RESULTS]]
    logger.info(f"{len(matches)} Treffer für '{query}'")
    return jsonify({"matches": matches})


@app.route('/detail', methods=['GET'])
def get_book_detail():
    """Details zu einem Hörspiel anhand der dreimetadaten-ID"""
    book_id = request.args.get('id')
    if not book_id or store.get() is None:
        return jsonify({})
    entry = store.by_id.get(book_id)
    return jsonify(transform_to_abs_format(entry) if entry else {})


@app.route('/name', methods=['GET'])
def get_provider_name():
    return jsonify({"name": "DreiMetadaten.de Provider"})


@app.route('/version', methods=['GET'])
def get_version():
    return jsonify({"version": VERSION})


@app.route('/health', methods=['GET'])
def health_check():
    """Health Check: lädt die Daten nur, wenn der Cache abgelaufen ist"""
    data = store.get()
    status = {
        "status": "healthy" if data is not None else "unhealthy",
        "entries": len(store.entries),
        "data_version": (data or {}).get("dbInfo", {}).get("version"),
        "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(store.loaded_at)) if store.loaded_at else None,
        "last_error": store.last_error,
    }
    return jsonify(status), 200 if data is not None else 503


if __name__ == '__main__':
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5000"))
    logger.info(f"Cover-Reihenfolge: {', '.join(COVER_PRIORITY)}")
    store.get()  # Daten beim Start laden
    try:
        from waitress import serve
        logger.info(f"Provider läuft auf http://{host}:{port}")
        serve(app, host=host, port=port)
    except ImportError:
        logger.warning("waitress nicht installiert - nutze den Flask-Entwicklungsserver")
        app.run(host=host, port=port)
