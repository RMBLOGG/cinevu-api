"""
Breezy API - Flask scraper untuk breezyandaman.com
Fix: session cookie sebelum AJAX, title strip, country/slug mapping
"""

from flask import Flask, jsonify, request, render_template
from bs4 import BeautifulSoup
import requests, re, os

app = Flask(__name__)

BASE_URL = "https://breezyandaman.com"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": BASE_URL,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8",
}

# Mapping slug lokal → slug situs
COUNTRY_MAP = {
    "jepang":   "japan",
    "filipina": "philippines",
    "inggris":  "uk",
    "korea":    "korea",
}

SEMI_MAP = {
    "indonesia":    "film-semi/semi-indonesia",
    "jepang":       "film-semi/semi-jepang",
    "korea":        "film-semi/semi-korea",
    "filipina":     "film-semi/semi-filipina",
    "bokep":        "film-bokep-jepang",
    "vivamax":      "vivamax",
    "kelas-bintang":"kelas-bintang",
}

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def make_session(referer_url=None):
    """Buat session baru dan visit halaman untuk dapat cookie."""
    s = requests.Session()
    s.headers.update(HEADERS)
    visit = referer_url or BASE_URL
    try:
        s.get(visit, timeout=12)
    except Exception as e:
        print(f"[session] gagal visit {visit}: {e}")
    return s

def get_soup(url, session=None):
    try:
        if session:
            r = session.get(url, timeout=15)
        else:
            r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"[get_soup] {e}")
    return None

def txt(el):
    return el.get_text(strip=True) if el else ""

def best_poster(img):
    if not img:
        return ""
    srcset = img.get("srcset", "")
    srcs = [s.strip().split(" ")[0] for s in srcset.split(",") if s.strip()]
    return srcs[-1] if srcs else (img.get("data-src") or img.get("src") or "")

def clean_title(raw):
    """Strip 'Permalink to: ' prefix dari title."""
    if not raw:
        return ""
    return raw.replace("Permalink to: ", "").strip()

def parse_movie_card(article):
    a = article.find("a", href=True)
    if not a:
        return None
    item = {
        "url":      a["href"],
        "title":    clean_title(a.get("title") or txt(article.find(re.compile(r"h\d")))),
        "poster":   best_poster(article.find("img")),
        "rating":   txt(article.find(class_="gmr-rating-item")).replace("\n", "").strip(),
        "quality":  txt(article.find(class_="gmr-quality-item")),
        "duration": txt(article.find(class_="gmr-duration-item")),
        "episodes": txt(article.find(class_="gmr-numbeps")).replace("Eps:", "").strip(),
    }
    return item if item["url"] else None

def parse_movie_list(soup):
    movies = []
    for art in soup.find_all("article"):
        m = parse_movie_card(art)
        if m:
            movies.append(m)
    return movies

def get_next_page_url(soup):
    nxt = soup.find("a", class_=re.compile(r"next", re.I))
    return nxt["href"] if nxt else None

def parse_detail(url, session=None):
    soup = get_soup(url, session=session)
    if not soup:
        return None

    data = {"url": url}

    t = soup.find("h1", class_="entry-title")
    data["title"] = txt(t)

    thumb = soup.find("div", class_="single-thumb")
    data["poster"] = best_poster(thumb.find("img") if thumb else None) or \
                     best_poster(soup.find("img", class_="wp-post-image"))

    data["rating"]       = txt(soup.find("span", itemprop="ratingValue"))
    data["rating_count"] = txt(soup.find("span", itemprop="ratingCount"))

    syn_div = soup.find("div", class_="entry-content-single")
    if syn_div:
        paras = [p.get_text(strip=True) for p in syn_div.find_all("p")
                 if len(p.get_text(strip=True)) > 40]
        data["synopsis"] = " ".join(paras[:3])
    else:
        data["synopsis"] = ""

    meta = {}
    for div in soup.find_all("div", class_="gmr-moviedata"):
        strong = div.find("strong")
        if not strong:
            continue
        label = txt(strong).rstrip(":").lower()
        links = [txt(a) for a in div.find_all("a")]
        if links:
            meta[label] = ", ".join(links)
        else:
            spans = [txt(el) for el in div.find_all(["span", "time"]) if txt(el)]
            if spans:
                meta[label] = ", ".join(spans)
            else:
                raw = div.get_text(strip=True).replace(txt(strong), "").strip()
                if raw:
                    meta[label] = raw
    data["meta"] = meta

    sw = soup.find(id="muvipro_player_content_id")
    data["post_id"] = sw.get("data-id") if sw else None

    trailer = soup.find("a", class_="gmr-trailer-popup")
    data["trailer"] = trailer["href"] if trailer else None

    episodes = []
    ep_div = soup.find("div", class_="gmr-listseries")
    if ep_div:
        for a in ep_div.find_all("a", class_="button"):
            episodes.append({
                "label": txt(a),
                "url":   a.get("href", ""),
                "title": a.get("title", ""),
            })
    data["episodes"] = episodes

    return data

def get_players(post_id, referer_url=None):
    """
    Fetch semua server player via AJAX.
    WAJIB visit halaman dulu (referer_url) agar cookie tersedia.
    """
    session = make_session(referer_url)
    players = []
    for tab in ["p1", "p2", "p3", "p4"]:
        try:
            r = session.post(
                AJAX_URL,
                data={
                    "action":  "muvipro_player_content",
                    "tab":     tab,
                    "post_id": post_id,
                },
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type":     "application/x-www-form-urlencoded",
                    "Referer":          referer_url or BASE_URL,
                },
                timeout=12,
            )
            if r.status_code == 200 and r.text.strip():
                inner  = BeautifulSoup(r.text, "html.parser")
                iframe = inner.find("iframe")
                if iframe:
                    src = iframe.get("src") or iframe.get("SRC") or ""
                    if src:
                        players.append({"server": tab, "url": src})
        except Exception as e:
            print(f"[player] {tab}: {e}")
    return players

def error(msg, code=400):
    return jsonify({"success": False, "error": msg}), code

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

# ── Movies terbaru ──
@app.route("/api/movies")
def movies():
    page = request.args.get("page", "1")
    url  = f"{BASE_URL}/" if page == "1" else f"{BASE_URL}/page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Search ──
@app.route("/api/search")
def search():
    q    = request.args.get("q", "")
    page = request.args.get("page", "1")
    if not q:
        return error("Parameter q diperlukan")
    base = f"{BASE_URL}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    url  = base if page == "1" else f"{BASE_URL}/page/{page}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success": True,
        "query":   q,
        "page":    int(page),
        "results": data,
        "total":   len(data),
    })

# ── Detail film ──
@app.route("/api/detail")
def detail():
    url = request.args.get("url", "")
    if not url:
        return error("Parameter url diperlukan")
    if not url.startswith(BASE_URL):
        return error("URL harus dari breezyandaman.com")
    # Gunakan session yang sudah visit halaman agar cookie ada
    session = make_session(url)
    data = parse_detail(url, session=session)
    if not data:
        return error("Gagal fetch detail", 500)
    return jsonify({"success": True, "data": data})

# ── Player (streaming links) ──
@app.route("/api/player")
def player():
    post_id = request.args.get("post_id", "")
    url     = request.args.get("url", "")   # referer opsional tapi dianjurkan
    if not post_id:
        return error("Parameter post_id diperlukan")
    players = get_players(post_id, referer_url=url or None)
    return jsonify({
        "success": True,
        "post_id": post_id,
        "players": players,
        "total":   len(players),
    })

# ── Episode detail + player ──
@app.route("/api/episode")
def episode():
    url = request.args.get("url", "")
    if not url:
        return error("Parameter url diperlukan")
    # Session visit dulu — cookie wajib untuk AJAX player
    session = make_session(url)
    soup    = get_soup(url, session=session)
    if not soup:
        return error("Gagal fetch", 500)

    data = {"url": url}
    t    = soup.find("h1", class_="entry-title") or soup.find("h1")
    data["title"] = txt(t)

    sw      = soup.find(id="muvipro_player_content_id")
    post_id = sw.get("data-id") if sw else None
    data["post_id"] = post_id

    if post_id:
        # Reuse session yang sudah punya cookie
        players = []
        for tab in ["p1", "p2", "p3", "p4"]:
            try:
                r = session.post(
                    AJAX_URL,
                    data={
                        "action":  "muvipro_player_content",
                        "tab":     tab,
                        "post_id": post_id,
                    },
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Content-Type":     "application/x-www-form-urlencoded",
                        "Referer":          url,
                    },
                    timeout=12,
                )
                if r.status_code == 200 and r.text.strip():
                    inner  = BeautifulSoup(r.text, "html.parser")
                    iframe = inner.find("iframe")
                    if iframe:
                        src = iframe.get("src") or iframe.get("SRC") or ""
                        if src:
                            players.append({"server": tab, "url": src})
            except Exception as e:
                print(f"[episode player] {tab}: {e}")
        data["players"] = players
    else:
        data["players"] = []

    return jsonify({"success": True, "data": data})

# ── Genre ──
@app.route("/api/genre/<slug>")
def genre(slug):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/{slug}/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Genre tidak ditemukan", 404)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "genre":     slug,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Tahun ──
@app.route("/api/year/<year>")
def by_year(year):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/year/{year}/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Tahun tidak ditemukan", 404)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "year":      year,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Negara ──
@app.route("/api/country/<country>")
def by_country(country):
    page = request.args.get("page", "1")
    slug = COUNTRY_MAP.get(country.lower(), country)  # mapping jepang→japan dll
    base = f"{BASE_URL}/country/{slug}/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Negara tidak ditemukan", 404)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "country":   country,
        "slug":      slug,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Series ──
@app.route("/api/series")
def series():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/tv/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Film Semi (root) ──
@app.route("/api/semi")
def semi():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/film-semi/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Semi sub-kategori ──
@app.route("/api/semi/<sub>")
def semi_sub(sub):
    page = request.args.get("page", "1")
    slug = SEMI_MAP.get(sub, f"film-semi/{sub}")
    base = f"{BASE_URL}/category/{slug}/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Kategori tidak ditemukan", 404)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "category":  sub,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Anime ──
@app.route("/api/anime")
def anime():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/animation/anime/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Hentai ──
@app.route("/api/hentai")
def hentai():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/animation/hentai/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Trending ──
@app.route("/api/trending")
def trending():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/trending/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ── Coming Soon ──
@app.route("/api/coming-soon")
def coming_soon():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/coming-soon/"
    url  = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    if not soup:
        return error("Gagal fetch", 500)
    data = parse_movie_list(soup)
    return jsonify({
        "success":   True,
        "page":      int(page),
        "results":   data,
        "total":     len(data),
        "next_page": get_next_page_url(soup),
    })

# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
