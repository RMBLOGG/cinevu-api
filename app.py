from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from bs4 import BeautifulSoup
from werkzeug.security import generate_password_hash, check_password_hash
import requests, re, os
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cinevu-secret-2026")

BASE_URL = "https://breezyandaman.com"
AJAX_URL = f"{BASE_URL}/wp-admin/admin-ajax.php"

SUPABASE_URL = "https://mafnnqttvkdgqqxczqyt.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im1hZm5ucXR0dmtkZ3FxeGN6cXl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE4NzQyMDEsImV4cCI6MjA4NzQ1MDIwMX0.YRh1oWVKnn4tyQNRbcPhlSyvr7V_1LseWN7VjcImb-Y"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "Referer": BASE_URL,
}

# ── Supabase helpers ──

def sb_headers(use_service=False):
    key = SUPABASE_SERVICE_KEY if use_service else SUPABASE_ANON_KEY
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def sb_get(table, params="", use_service=False):
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}?{params}",
                         headers=sb_headers(use_service), timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []

def sb_post(table, data, use_service=False):
    try:
        r = requests.post(f"{SUPABASE_URL}/rest/v1/{table}",
                          json=data, headers=sb_headers(use_service), timeout=10)
        return r.json(), r.status_code
    except Exception as e:
        return {"error": str(e)}, 500

def sb_patch(table, row_id, data, use_service=False):
    try:
        r = requests.patch(f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}",
                           json=data, headers=sb_headers(use_service), timeout=10)
        return r.status_code
    except:
        return 500

def sb_delete(table, row_id, use_service=False):
    try:
        r = requests.delete(f"{SUPABASE_URL}/rest/v1/{table}?id=eq.{row_id}",
                            headers=sb_headers(use_service), timeout=10)
        return r.status_code
    except:
        return 500

# ── Auth decorator ──

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated

# ── Iklan helper ──

def get_iklan_by_posisi(posisi):
    today = datetime.now().strftime("%Y-%m-%d")
    rows = sb_get("iklan_aktif",
        f"posisi=eq.{posisi}&aktif=eq.true&order=prioritas.asc",
        use_service=True)
    result = []
    for r in rows:
        mulai = r.get("tanggal_mulai")
        selesai = r.get("tanggal_selesai")
        if mulai and mulai > today:
            continue
        if selesai and selesai < today:
            continue
        result.append(r)
    return result

def get_all_iklan_posisi():
    posisi_list = ["header_banner","footer_banner","sidebar","popup",
                   "watch_before","watch_after","home_mid"]
    return {p: get_iklan_by_posisi(p) for p in posisi_list}

# ── Scraper helpers ──

def get_soup(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"Error: {e}")
    return None

def txt(el):
    return el.get_text(strip=True) if el else ""

def best_poster(img):
    if not img:
        return ""
    srcset = img.get("srcset", "")
    srcs = [s.strip().split(" ")[0] for s in srcset.split(",") if s.strip()]
    url = srcs[-1] if srcs else (img.get("data-src") or img.get("src") or "")
    url = re.sub(r"-\d+x\d+(\.[a-zA-Z]+)$", r"\1", url)
    return url

def clean_title(raw):
    if not raw:
        return ""
    raw = re.sub(r'^Permalink to\s*:\s*', '', raw, flags=re.I)
    return raw.strip()

def parse_cards(soup):
    movies = []
    for art in soup.find_all("article"):
        a = art.find("a", href=True)
        if not a:
            continue
        heading = art.find(re.compile(r"h\d"))
        title = txt(heading) if heading else ""
        if not title:
            img = art.find("img")
            title = img.get("alt","").strip() if img else ""
        if not title:
            title = clean_title(a.get("title",""))
        item = {
            "url":      a["href"],
            "title":    title,
            "poster":   best_poster(art.find("img")),
            "rating":   txt(art.find(class_="gmr-rating-item")).strip(),
            "quality":  txt(art.find(class_="gmr-quality-item")),
            "duration": txt(art.find(class_="gmr-duration-item")),
            "episodes": txt(art.find(class_="gmr-numbeps")).replace("Eps:","").strip(),
        }
        if item["url"] and item["title"]:
            movies.append(item)
    return movies

def get_next_page(soup):
    nxt = soup.find("a", class_=re.compile(r"next", re.I))
    return nxt["href"] if nxt else None

def parse_detail(url):
    soup = get_soup(url)
    if not soup:
        return None
    data = {"url": url}
    t = soup.find("h1", class_="entry-title")
    data["title"] = txt(t)
    thumb = soup.find("div", class_="single-thumb")
    data["poster"] = best_poster(thumb.find("img") if thumb else None) or best_poster(soup.find("img", class_="wp-post-image"))
    data["rating"] = txt(soup.find("span", itemprop="ratingValue"))
    data["rating_count"] = txt(soup.find("span", itemprop="ratingCount"))
    syn_div = soup.find("div", class_="entry-content-single")
    if syn_div:
        paras = [p.get_text(strip=True) for p in syn_div.find_all("p") if len(p.get_text(strip=True)) > 40]
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
            spans = [txt(el) for el in div.find_all(["span","time"]) if txt(el)]
            meta[label] = ", ".join(spans) if spans else div.get_text(strip=True).replace(txt(strong),"").strip()
    data["meta"] = meta
    sw = soup.find(id="muvipro_player_content_id")
    data["post_id"] = sw.get("data-id") if sw else None
    trailer = soup.find("a", class_="gmr-trailer-popup")
    data["trailer"] = trailer["href"] if trailer else None
    episodes = []
    ep_div = soup.find("div", class_="gmr-listseries")
    if ep_div:
        for a in ep_div.find_all("a", class_="button"):
            episodes.append({"label": txt(a), "url": a.get("href",""), "title": a.get("title","")})
    data["episodes"] = episodes
    related = []
    for sec in soup.find_all("div", class_="gmr-box-content"):
        for art in sec.find_all("article")[:8]:
            m = parse_cards(BeautifulSoup(str(art), "html.parser"))
            related.extend(m)
    data["related"] = related[:8]
    return data

def get_players(post_id):
    session_r = requests.Session()
    session_r.headers.update(HEADERS)
    players = []
    for tab in ["p1","p2","p3","p4"]:
        try:
            r = session_r.post(AJAX_URL, data={"action":"muvipro_player_content","tab":tab,"post_id":post_id}, timeout=10)
            if r.status_code == 200 and r.text.strip():
                inner = BeautifulSoup(r.text, "html.parser")
                iframe = inner.find("iframe")
                if iframe:
                    src = iframe.get("src") or iframe.get("SRC") or ""
                    if src:
                        players.append({"server": tab.upper(), "url": src})
        except:
            pass
    return players

# ══════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════

@app.route("/")
def home():
    page = request.args.get("page", "1")
    iklan = get_all_iklan_posisi()

    def fetch(url):
        s = get_soup(url)
        return parse_cards(s)[:12] if s else []

    if page == "1":
        sections = [
            {"id": "terbaru",  "title": "Film Terbaru",    "url": f"{BASE_URL}/",                          "more": "/?page=2"},
            {"id": "trending", "title": "Trending",         "url": f"{BASE_URL}/category/trending/",        "more": "/genre/trending"},
            {"id": "series",   "title": "Series & TV Show", "url": f"{BASE_URL}/tv/",                       "more": "/series"},
            {"id": "anime",    "title": "Anime",             "url": f"{BASE_URL}/category/animation/anime/","more": "/anime"},
            {"id": "action",   "title": "Action",            "url": f"{BASE_URL}/category/action/",         "more": "/genre/action"},
            {"id": "horror",   "title": "Horror",            "url": f"{BASE_URL}/category/horror/",         "more": "/genre/horror"},
            {"id": "korea",    "title": "Film Korea",        "url": f"{BASE_URL}/country/korea/",           "more": "/country/korea"},
            {"id": "indo",     "title": "Film Indonesia",    "url": f"{BASE_URL}/country/indonesia/",       "more": "/country/indonesia"},
            {"id": "semi",     "title": "Film Semi",         "url": f"{BASE_URL}/category/film-semi/",      "more": "/semi"},
        ]
        for sec in sections:
            sec["movies"] = fetch(sec["url"])
        return render_template("home.html", sections=sections, page=1, active="home", iklan=iklan)
    else:
        url = f"{BASE_URL}/page/{page}/"
        soup = get_soup(url)
        movies = parse_cards(soup) if soup else []
        next_page = get_next_page(soup) if soup else None
        return render_template("list.html", movies=movies, page=int(page), title="Film Terbaru",
                               next_page=next_page, active="home", iklan=get_all_iklan_posisi())

@app.route("/series")
def series():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/tv/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Series",
                           next_page=get_next_page(soup), active="series", iklan=get_all_iklan_posisi())

@app.route("/anime")
def anime():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/animation/anime/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Anime",
                           next_page=get_next_page(soup), active="anime", iklan=get_all_iklan_posisi())

@app.route("/semi")
def semi():
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/film-semi/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title="Film Semi",
                           next_page=get_next_page(soup), active="semi", iklan=get_all_iklan_posisi())

@app.route("/genre/<slug>")
def genre(slug):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/category/{slug}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page),
                           title=slug.replace("-"," ").title(), next_page=get_next_page(soup),
                           active="", iklan=get_all_iklan_posisi())

@app.route("/year/<year>")
def by_year(year):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/year/{year}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=f"Film Tahun {year}",
                           next_page=get_next_page(soup), active="", iklan=get_all_iklan_posisi())

@app.route("/country/<country>")
def by_country(country):
    page = request.args.get("page", "1")
    base = f"{BASE_URL}/country/{country}/"
    url = base if page == "1" else f"{base}page/{page}/"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=country.title(),
                           next_page=get_next_page(soup), active="", iklan=get_all_iklan_posisi())

@app.route("/search")
def search():
    q = request.args.get("q", "")
    page = request.args.get("page", "1")
    if not q:
        return redirect(url_for("home"))
    url = f"{BASE_URL}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    if page != "1":
        url = f"{BASE_URL}/page/{page}/?s={requests.utils.quote(q)}&post_type[]=post&post_type[]=tv"
    soup = get_soup(url)
    movies = parse_cards(soup) if soup else []
    return render_template("list.html", movies=movies, page=int(page), title=f'Hasil: "{q}"',
                           next_page=get_next_page(soup), active="", query=q,
                           iklan=get_all_iklan_posisi())

@app.route("/watch")
def watch():
    url = request.args.get("url", "")
    if not url:
        return redirect(url_for("home"))
    data = parse_detail(url)
    if not data:
        return redirect(url_for("home"))
    return render_template("watch.html", movie=data, active="", iklan=get_all_iklan_posisi())

@app.route("/api/player")
def api_player():
    post_id = request.args.get("post_id", "")
    if not post_id:
        return jsonify({"error": "post_id required"}), 400
    players = get_players(post_id)
    return jsonify({"players": players})

# ── Pasang Iklan (publik) ──

@app.route("/pasang-iklan")
def pasang_iklan():
    return render_template("pasang_iklan.html", active="", iklan=get_all_iklan_posisi())

@app.route("/api/iklan/submit", methods=["POST"])
def iklan_submit():
    d = request.get_json() or {}
    required = ["nama_brand","email","no_hp","jenis_iklan","budget","durasi_tayang"]
    for f in required:
        if not d.get(f):
            return jsonify({"error": f"Field {f} wajib diisi"}), 400
    payload = {
        "nama_brand":   d["nama_brand"],
        "email":        d["email"],
        "no_hp":        d["no_hp"],
        "jenis_iklan":  d["jenis_iklan"],
        "budget":       d["budget"],
        "durasi_tayang":d["durasi_tayang"],
        "pesan":        d.get("pesan",""),
        "materi_url":   d.get("materi_url",""),
        "status":       "pending"
    }
    result, code = sb_post("iklan_requests", payload, use_service=True)
    if code in (200, 201):
        return jsonify({"ok": True, "message": "Permintaan iklan berhasil dikirim!"})
    return jsonify({"error": "Gagal menyimpan data"}), 500

# ══════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    error = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        rows = sb_get("cinevu_admins", f"username=eq.{username}&limit=1", use_service=True)
        if rows and check_password_hash(rows[0]["password_hash"], password):
            session["admin_logged_in"] = True
            session["admin_username"] = username
            session["admin_display"] = rows[0].get("display_name","Admin")
            return redirect(url_for("admin_dashboard"))
        error = "Username atau password salah"
    return render_template("admin/login.html", error=error)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    requests_all = sb_get("iklan_requests", "order=created_at.desc", use_service=True)
    iklan_all    = sb_get("iklan_aktif",    "order=created_at.desc", use_service=True)
    stats = {
        "total_request": len(requests_all),
        "pending":       sum(1 for r in requests_all if r.get("status") == "pending"),
        "approved":      sum(1 for r in requests_all if r.get("status") == "approved"),
        "iklan_aktif":   sum(1 for i in iklan_all if i.get("aktif")),
    }
    return render_template("admin/dashboard.html",
                           stats=stats,
                           recent_requests=requests_all[:5],
                           admin_name=session.get("admin_display","Admin"))

# ── Admin: Kelola Requests ──

@app.route("/admin/requests")
@admin_required
def admin_requests():
    status_filter = request.args.get("status", "all")
    params = "order=created_at.desc"
    if status_filter != "all":
        params += f"&status=eq.{status_filter}"
    rows = sb_get("iklan_requests", params, use_service=True)
    return render_template("admin/requests.html",
                           rows=rows,
                           status_filter=status_filter,
                           admin_name=session.get("admin_display","Admin"))

@app.route("/admin/requests/update", methods=["POST"])
@admin_required
def admin_request_update():
    d = request.get_json() or {}
    row_id = d.get("id")
    if not row_id:
        return jsonify({"error": "id required"}), 400
    payload = {
        "status":         d.get("status"),
        "catatan_admin":  d.get("catatan_admin",""),
        "updated_at":     datetime.now().isoformat()
    }
    code = sb_patch("iklan_requests", row_id, payload, use_service=True)
    return jsonify({"ok": code in (200,204)})

@app.route("/admin/requests/delete", methods=["POST"])
@admin_required
def admin_request_delete():
    d = request.get_json() or {}
    row_id = d.get("id")
    if not row_id:
        return jsonify({"error": "id required"}), 400
    code = sb_delete("iklan_requests", row_id, use_service=True)
    return jsonify({"ok": code in (200,204)})

# ── Admin: Kelola Iklan Aktif ──

@app.route("/admin/iklan")
@admin_required
def admin_iklan():
    rows = sb_get("iklan_aktif", "order=created_at.desc", use_service=True)
    return render_template("admin/iklan.html",
                           rows=rows,
                           admin_name=session.get("admin_display","Admin"))

@app.route("/admin/iklan/tambah", methods=["POST"])
@admin_required
def admin_iklan_tambah():
    d = request.get_json() or {}
    required = ["nama","posisi","tipe","konten"]
    for f in required:
        if not d.get(f):
            return jsonify({"error": f"Field {f} wajib diisi"}), 400
    payload = {
        "nama":            d["nama"],
        "posisi":          d["posisi"],
        "tipe":            d["tipe"],
        "konten":          d["konten"],
        "link_url":        d.get("link_url",""),
        "aktif":           d.get("aktif", True),
        "prioritas":       int(d.get("prioritas", 1)),
        "tanggal_mulai":   d.get("tanggal_mulai") or None,
        "tanggal_selesai": d.get("tanggal_selesai") or None,
        "catatan":         d.get("catatan",""),
        "dibuat_oleh":     session.get("admin_username","admin")
    }
    result, code = sb_post("iklan_aktif", payload, use_service=True)
    if code in (200, 201):
        return jsonify({"ok": True})
    return jsonify({"error": "Gagal menyimpan"}), 500

@app.route("/admin/iklan/update", methods=["POST"])
@admin_required
def admin_iklan_update():
    d = request.get_json() or {}
    row_id = d.get("id")
    if not row_id:
        return jsonify({"error": "id required"}), 400
    payload = {k: v for k, v in {
        "nama":            d.get("nama"),
        "posisi":          d.get("posisi"),
        "tipe":            d.get("tipe"),
        "konten":          d.get("konten"),
        "link_url":        d.get("link_url"),
        "aktif":           d.get("aktif"),
        "prioritas":       d.get("prioritas"),
        "tanggal_mulai":   d.get("tanggal_mulai") or None,
        "tanggal_selesai": d.get("tanggal_selesai") or None,
        "catatan":         d.get("catatan"),
        "updated_at":      datetime.now().isoformat()
    }.items() if v is not None}
    code = sb_patch("iklan_aktif", row_id, payload, use_service=True)
    return jsonify({"ok": code in (200,204)})

@app.route("/admin/iklan/toggle", methods=["POST"])
@admin_required
def admin_iklan_toggle():
    d = request.get_json() or {}
    row_id = d.get("id")
    aktif   = d.get("aktif")
    if row_id is None or aktif is None:
        return jsonify({"error": "id & aktif required"}), 400
    code = sb_patch("iklan_aktif", row_id, {"aktif": aktif, "updated_at": datetime.now().isoformat()}, use_service=True)
    return jsonify({"ok": code in (200,204)})

@app.route("/admin/iklan/delete", methods=["POST"])
@admin_required
def admin_iklan_delete():
    d = request.get_json() or {}
    row_id = d.get("id")
    if not row_id:
        return jsonify({"error": "id required"}), 400
    code = sb_delete("iklan_aktif", row_id, use_service=True)
    return jsonify({"ok": code in (200,204)})

# ── API: get iklan untuk render ──
@app.route("/api/iklan/<posisi>")
def api_iklan(posisi):
    rows = get_iklan_by_posisi(posisi)
    return jsonify({"iklan": rows})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
