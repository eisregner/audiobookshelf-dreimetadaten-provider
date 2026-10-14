import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import abs_dreimetadata as provider  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.json")


class FakeResponse:
    def __init__(self, status_code=200, data=None, etag=None):
        self.status_code = status_code
        self._data = data
        self.headers = {"ETag": etag} if etag else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


@pytest.fixture
def data():
    with open(FIXTURE, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def calls(monkeypatch, data):
    """Ersetzt den Download durch die Testdaten und zählt die Abrufe"""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(headers or {})
        return FakeResponse(200, data, etag='"v1"')

    monkeypatch.setattr(provider.requests, "get", fake_get)
    monkeypatch.setattr(provider, "store", provider.MetadataStore("http://test", ttl=3600))
    return calls


@pytest.fixture
def client(calls):
    return provider.app.test_client()


def search(client, query):
    return client.get("/search", query_string={"query": query}).get_json()["matches"]


def first(client, query):
    matches = search(client, query)
    assert matches, f"keine Treffer für {query!r}"
    m = matches[0]
    return m["title"], m["series"][0]["series"], m["series"][0].get("sequence")


# --- Suche ---

@pytest.mark.parametrize("query, expected", [
    ("Super-Papagei", ("und der Super-Papagei", "Die drei ???", "1")),
    ("super papagei", ("und der Super-Papagei", "Die drei ???", "1")),
    ("Supper-Papagei", ("und der Super-Papagei", "Die drei ???", "1")),
    ("Die drei ??? und der Super-Papagei", ("und der Super-Papagei", "Die drei ???", "1")),
    ("Die drei Fragezeichen - Folge 1 - und der Super-Papagei", ("und der Super-Papagei", "Die drei ???", "1")),
    ("Die drei ??? - 006 - und der sprechende Totenkopf", ("und der sprechende Totenkopf", "Die drei ???", "6")),
    ("006 - Die drei ??? und der sprechende Totenkopf", ("und der sprechende Totenkopf", "Die drei ???", "6")),
    ("6", ("und der sprechende Totenkopf", "Die drei ???", "6")),
    ("Folge 6", ("und der sprechende Totenkopf", "Die drei ???", "6")),
    ("Folge 006", ("und der sprechende Totenkopf", "Die drei ???", "6")),
    ("Die drei ??? 100", ("Toteninsel", "Die drei ???", "100")),
    ("Kids 6", ("Gefahr im Gruselgarten", "Die drei ??? Kids", "6")),
    ("Die drei ??? Kids 6 Gefahr im Gruselgarten", ("Gefahr im Gruselgarten", "Die drei ??? Kids", "6")),
    ("DiE DR3i 6", ("Tödliche Regie", "DiE DR3i", "6")),
    ("Gefahr im Gruselgarten", ("Gefahr im Gruselgarten", "Die drei ??? Kids", "6")),
    # Zahlen im Titel dürfen nicht als Folgennummer gewinnen (Hauptserie 100 = Toteninsel, Kids 24 = Im Bann des Zauberers)
    ("100 Stunden", ("100 Stunden", "Die drei ??? Kids", "100")),
    ("Adventskalender: 24 Tage im Weihnachtsland", ("Adventskalender: 24 Tage im Weihnachtsland", "Die drei ??? Kids", None)),
])
def test_search_top_match(client, query, expected):
    assert first(client, query) == expected


def test_search_empty_query(client):
    assert search(client, "") == []


def test_search_unrelated_query_has_no_matches(client):
    assert search(client, "Harry Potter und der Stein der Weisen") == []


def test_search_unknown_title_ignores_filler_words(client):
    assert search(client, "Die drei ??? Kids und der Gruselturm") == []


def test_search_prefix_and_number_only_matches_number(client):
    assert [m["title"] for m in search(client, "Die drei ??? 100")] == ["Toteninsel", "100 Stunden"]


def test_search_number_only_returns_all_series_with_hauptserie_first(client):
    series = [m["series"][0]["series"] for m in search(client, "6")]
    assert series[0] == "Die drei ???"
    assert sorted(series[1:]) == ["DiE DR3i", "Die drei ??? Kids"]


def test_search_limits_results(client):
    assert len(search(client, "und")) <= provider.MAX_RESULTS


# --- Umwandlung ins ABS-Format ---

def abs_entry(client, title):
    client.get("/health")  # lädt die Daten
    entry = next(e for e in provider.store.entries if e["episode"]["titel"] == title)
    return provider.transform_to_abs_format(entry)


def test_duration_in_minutes(client):
    assert abs_entry(client, "und der Super-Papagei")["duration"] == 52


def test_duration_counts_all_media(client):
    # Toteninsel hat 3 CDs mit zusammen ~167 Minuten
    assert abs_entry(client, "Toteninsel")["duration"] == 167


def test_duration_fallback_sums_all_media():
    episode = {"medien": [{"tracks": [{"end": 1_800_000}]}, {"tracks": [{"start": 0, "end": 1_200_000}]}]}
    assert provider.duration_minutes(episode) == 50


def test_duration_missing():
    assert provider.duration_minutes({}) is None


def test_spezial_sequence_follows_position(client):
    sequences = [abs_entry(client, t)["series"][0]["sequence"] for t in
                 ("Master of Chess (Live & Unplugged)", "und der Super-Papagei 2004", "und der dreiTag")]
    assert sequences == ["1", "2", "3"]


def test_entries_without_number_have_no_sequence(client):
    assert abs_entry(client, "Hotel Luxury End")["series"] == [{"series": "DiE DR3i"}]
    assert abs_entry(client, "Rocky Beach Radio Show")["series"] == [{"series": "Sonstige"}]


def test_no_asin(client):
    assert "asin" not in abs_entry(client, "und der Super-Papagei")


def test_narrators_keep_role_order(client):
    narrators = abs_entry(client, "und der Super-Papagei")["narrator"].split(", ")
    assert narrators[:4] == ["Peter Pasetti", "Oliver Rohrbeck", "Jens Wawrczeck", "Andreas Fröhlich"]
    assert len(narrators) == len(set(narrators))


def test_narrators_split_and_deduplicate():
    rollen = [{"rolle": "A", "sprecher": "X"}, {"rolle": "B", "sprecher": "Y, X"}, {"rolle": "C", "sprecher": "Z"}]
    assert provider.extract_narrators(rollen) == "X, Y, Z"


def test_tags(client):
    assert abs_entry(client, "und der Super-Papagei")["tags"] == ["Jahr 1979"]
    assert abs_entry(client, "und der dreiTag")["tags"] == ["Jahr 2010", "Spezialfolge", "Mehrteilig"]


def test_cover_uses_https(client):
    assert abs_entry(client, "und der Super-Papagei")["cover"] == "https://dreimetadaten.de/data/Serie/001/cover.png"


@pytest.mark.parametrize("links, expected", [
    ({"cover": "/data/x.png"}, "https://dreimetadaten.de/data/x.png"),
    ({"cover": "data/x.png"}, "https://dreimetadaten.de/data/x.png"),
    ({"cover_itunes": "https://a.example/c.jpg"}, "https://a.example/c.jpg"),
    ({"cover2": ["http://dreimetadaten.de/y.png"]}, "https://dreimetadaten.de/y.png"),
    ({}, ""),
])
def test_cover_fallbacks(links, expected):
    assert provider.extract_cover_url(links) == expected


ALL_COVERS = {
    "cover": "http://dreimetadaten.de/data/Serie/001/cover.png",
    "artwork": "http://dreimetadaten.de/data/Serie/001/artwork.webp",
    "cover_itunes": "http://a1.mzstatic.com/source",
    "cover_dreifragezeichen": "https://cdn-p.smehost.net/ddf_cd_001.jpg",
    "cover_kosmos": "http://web.archive.org/kosmos.jpg",
}


@pytest.mark.parametrize("setting, expected", [
    ("", "https://dreimetadaten.de/data/Serie/001/cover.png"),
    ("apple", "https://a1.mzstatic.com/source"),
    ("dreifragezeichen", "https://cdn-p.smehost.net/ddf_cd_001.jpg"),
    ("artwork", "https://dreimetadaten.de/data/Serie/001/artwork.webp"),
    (" Kosmos , apple ", "https://web.archive.org/kosmos.jpg"),
    ("unbekannt,apple", "https://a1.mzstatic.com/source"),
])
def test_cover_priority(monkeypatch, setting, expected):
    monkeypatch.setattr(provider, "COVER_PRIORITY", provider.parse_cover_priority(setting))
    assert provider.extract_cover_url(ALL_COVERS) == expected


def test_cover_priority_falls_back_when_variant_missing(monkeypatch):
    # Kids-Folgen haben kein eigenes Cover von dreimetadaten.de
    monkeypatch.setattr(provider, "COVER_PRIORITY", provider.parse_cover_priority("artwork,dreimetadaten"))
    kids_links = {k: v for k, v in ALL_COVERS.items() if k in ("cover_itunes", "cover_dreifragezeichen")}
    assert provider.extract_cover_url(kids_links) == "https://a1.mzstatic.com/source"


def test_parse_cover_priority():
    assert provider.parse_cover_priority("") == ["dreimetadaten", "apple", "dreifragezeichen", "kosmos"]
    assert provider.parse_cover_priority("apple,APPLE,foo") == ["apple", "dreimetadaten", "dreifragezeichen", "kosmos"]


def test_kids_cover_uses_apple_by_default(client):
    assert "mzstatic.com" in abs_entry(client, "Gefahr im Gruselgarten")["cover"]


def test_matches_follow_abs_spec(client):
    allowed = {"title", "subtitle", "author", "narrator", "publisher", "publishedYear", "description", "cover",
               "isbn", "asin", "genres", "tags", "series", "language", "duration"}
    for match in search(client, "und der"):
        assert set(match) <= allowed
        assert isinstance(match["title"], str) and match["title"]
        assert isinstance(match.get("duration", 0), int)


def test_detail_by_id(client, data):
    drei_id = data["serie"][0]["ids"]["dreimetadaten"]
    detail = client.get("/detail", query_string={"id": drei_id}).get_json()
    assert detail["title"] == "und der Super-Papagei"
    assert client.get("/detail", query_string={"id": "999999"}).get_json() == {}


# --- Cache, Health Check, Auth ---

def test_data_is_downloaded_once(client, calls):
    for _ in range(5):
        search(client, "Papagei")
        client.get("/health")
    assert len(calls) == 1


def test_refresh_uses_etag_and_keeps_data_on_304(client, calls, monkeypatch):
    search(client, "Papagei")
    provider.store.checked_at = 0  # Cache abgelaufen
    monkeypatch.setattr(provider.requests, "get", lambda url, headers=None, timeout=None:
                        calls.append(headers) or FakeResponse(304))
    assert first(client, "Papagei")[0] == "und der Super-Papagei"
    assert calls[-1] == {"If-None-Match": '"v1"'}


def test_keeps_stale_data_when_download_fails(client, monkeypatch):
    search(client, "Papagei")
    provider.store.checked_at = 0

    def failing_get(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(provider.requests, "get", failing_get)
    assert first(client, "Papagei")[0] == "und der Super-Papagei"
    health = client.get("/health")
    assert health.status_code == 200
    assert health.get_json()["last_error"] == "offline"


def test_health_unhealthy_without_data(monkeypatch):
    def failing_get(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(provider.requests, "get", failing_get)
    monkeypatch.setattr(provider, "store", provider.MetadataStore("http://test", ttl=3600))
    client = provider.app.test_client()
    assert client.get("/health").status_code == 503
    assert client.get("/search", query_string={"query": "Papagei"}).status_code == 500


def test_health_reports_data_version(client, data):
    body = client.get("/health").get_json()
    assert body["status"] == "healthy"
    assert body["data_version"] == data["dbInfo"]["version"]
    assert body["entries"] == 20


def test_api_key(client, monkeypatch):
    monkeypatch.setattr(provider, "API_KEY", "geheim")
    assert client.get("/search", query_string={"query": "Papagei"}).status_code == 401
    ok = client.get("/search", query_string={"query": "Papagei"}, headers={"AUTHORIZATION": "geheim"})
    assert ok.status_code == 200
    assert client.get("/health").status_code == 200  # Health Check bleibt offen
