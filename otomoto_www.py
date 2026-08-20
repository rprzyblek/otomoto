import json
import os
import re
import sqlite3
from datetime import datetime
import pandas as pd
import requests
import streamlit as st

# --- KONFIGURACJA STRONY ---
st.set_page_config(
    page_title="Otomoto Price Tracker", 
    page_icon="🚗", 
    layout="centered"
)

# --- MAPOWANIE MIESIĘCY ---
MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12
}

# --- BAZA DANYCH (SQLite) ---
DB_NAME = "price_tracker.db"

def init_db():
    """Inicjalizacja tabeli oraz migracja bazy danych."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            price REAL,
            is_active INTEGER DEFAULT 1,
            timestamp DATETIME NOT NULL,
            image_url TEXT,
            published_at TEXT,
            location TEXT
        )
    ''')
    
    for col in ["title TEXT", "is_active INTEGER DEFAULT 1", "published_at TEXT", "location TEXT"]:
        try:
            c.execute(f"ALTER TABLE price_history ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass

    conn.commit()
    conn.close()

def save_price_entry(url, title, price, is_active, image_url, published_at, location):
    """Zapisuje nowy pomiar ceny/statusu oraz lokalizację."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_int = 1 if is_active else 0
    price_to_save = float(price) if price is not None else None

    c.execute(
        "INSERT INTO price_history (url, title, price, is_active, timestamp, image_url, published_at, location) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (url, title, price_to_save, active_int, now, image_url, published_at, location)
    )
    conn.commit()
    conn.close()

def delete_offer(url):
    """Usuwa całą historię powiązaną z danym URL."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM price_history WHERE url = ?", (url,))
    conn.commit()
    conn.close()

def parse_publication_date(date_str):
    """Konwertuje napis np. '17 sierpnia 2026 12:51' na obiekt datetime."""
    if not date_str:
        return None
    try:
        match = re.search(r'(\d{1,2})\s+([a-złóężąśćźń]+)\s+(\d{4})', date_str, re.IGNORECASE)
        if match:
            day = int(match.group(1))
            month_str = match.group(2).lower()
            year = int(match.group(3))
            month = MONTHS_PL.get(month_str, 1)
            return datetime(year, month, day)
    except Exception:
        pass
    return None

def extract_brand(title):
    """Wyciąga pierwszą nazwę (markę) z tytułu ogłoszenia."""
    if not title or title == "Ogłoszenie Otomoto":
        return "Inne"
    parts = title.strip().split()
    return parts[0].capitalize() if parts else "Inne"

def clean_location(raw_loc):
    """Oczyszcza napis z adresu, usuwając wstrzyknięte style CSS, ikony i zbędne frazy."""
    if not raw_loc or "Zobacz więcej" in raw_loc or "oferty" in raw_loc.lower():
        return None
    
    loc = re.sub(r'\.[a-zA-Z0-9_-]+\s*\{[^}]*\}', '', raw_loc)
    loc = re.sub(r'<[^>]+>', '', loc)
    loc = re.sub(r'^\d{2}-\d{3}\s*', '', loc)
    loc = re.sub(r'.*?-\s*\d{2}-\d{3}\s*', '', loc)
    loc = re.sub(r'\s*\(Polska\)', '', loc, flags=re.IGNORECASE)
    
    loc = loc.strip()
    return loc if loc else None

def get_tracked_summary():
    """Pobiera zestawienie śledzonych ofert."""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(
        "SELECT url, title, price, is_active, timestamp, image_url, published_at, location FROM price_history ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    if df.empty:
        return []

    summary = []
    grouped = df.groupby('url')
    now_dt = datetime.now()

    for url, group in grouped:
        first_entry = group.iloc[0]
        latest_entry = group.iloc[-1]

        title = latest_entry['title'] if pd.notna(latest_entry['title']) and latest_entry['title'] else "Ogłoszenie Otomoto"
        is_active = bool(latest_entry['is_active']) if pd.notna(latest_entry['is_active']) else True
        
        current_price = latest_entry['price']
        first_price = first_entry['price']
        
        diff = 0
        if current_price is not None and first_price is not None:
            diff = current_price - first_price

        image_url = latest_entry['image_url']
        published_at_str = latest_entry['published_at'] or first_entry['published_at']
        location_str = latest_entry['location'] if pd.notna(latest_entry['location']) else first_entry['location']

        pub_dt = parse_publication_date(published_at_str)
        if pub_dt:
            days_on_market = (now_dt - pub_dt).days
        else:
            first_seen_dt = datetime.strptime(first_entry['timestamp'], "%Y-%m-%d %H:%M:%S")
            days_on_market = (now_dt - first_seen_dt).days

        summary.append({
            'url': url,
            'title': title,
            'brand': extract_brand(title),
            'current_price': current_price if current_price is not None else 0,
            'is_active': is_active,
            'diff': diff,
            'image_url': image_url,
            'days_on_market': days_on_market,
            'published_at': published_at_str,
            'location': location_str,
            'last_updated': latest_entry['timestamp']
        })

    return summary

init_db()

# --- SCRAPER ---
def sprawdz_i_pobierz_otomoto(url):
    """Pobiera nazwę, cenę, zdjęcie, datę oraz dokładną lokalizację z Otomoto."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
        "Cache-Control": "no-cache",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code in [403, 404, 410]:
            return None, None, False, None, None, None

        html = response.text

        if "Ogłoszenie jest nieaktualne" in html or "To ogłoszenie nie jest już dostępne" in html:
            return None, None, False, None, None, None

        title = None
        cena = None
        url_zdjecia = None
        published_at = None
        location = None

        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if match:
            json_data = json.loads(match.group(1))
            ad_data = json_data.get("props", {}).get("pageProps", {}).get("ad", {})

            if ad_data:
                title = ad_data.get("title")
                if ad_data.get("price") and "value" in ad_data["price"]:
                    cena = float(ad_data["price"]["value"])
                photos = ad_data.get("photos", [])

                if photos:
                    url_zdjecia = photos[0].get("url") or photos[0].get("medium")

                published_at = ad_data.get("createdTime") or ad_data.get("createdAt")
                
                loc_data = ad_data.get("location", {})
                if loc_data:
                    city = loc_data.get("city", {}).get("name", "")
                    region = loc_data.get("region", {}).get("name", "")
                    if city and region:
                        location = clean_location(f"{city}, {region}")
                    elif city:
                        location = clean_location(city)

        if not location:
            loc_matches = re.findall(
                r'<p[^>]*class="[^"]*ooa-889rdv[^"]*"[^>]*>(.*?)</p>',
                html, re.DOTALL | re.IGNORECASE
            )
            for loc_raw in loc_matches:
                cand_loc = clean_location(loc_raw)
                if cand_loc:
                    location = cand_loc
                    break

        if not published_at:
            date_match = re.search(
                r'<p[^>]*class="[^"]*text-foreground-secondary[^"]*"[^>]*>(\d{1,2}\s+[a-złóężąśćźń]+\s+\d{4}[^<]*)</p>',
                html, re.IGNORECASE
            )
            if date_match:
                published_at = date_match.group(1).strip()

        if not title:
            h1_match = re.search(r'<h1[^>]*class="[^"]*offer-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            if not h1_match:
                h1_match = re.search(r'<h1[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
                
            if h1_match:
                title_raw = h1_match.group(1)
                title = re.sub(r'<[^>]+>', '', title_raw).strip()

        if cena is None:
            price_match = re.search(r"(\d[\d\s]+)\s*PLN", html)
            if price_match:
                clean = "".join(re.findall(r"\d+", price_match.group(1)))
                if clean:
                    cena = float(clean)

        if not url_zdjecia:
            og_image_match = re.search(r'<meta property="og:image" content="(.*?)"', html)
            if og_image_match:
                url_zdjecia = og_image_match.group(1)

        final_title = title if title else "Ogłoszenie Otomoto"

        if cena is not None:
            return final_title, cena, True, url_zdjecia, published_at, location

    except Exception as e:
        st.error(f"Błąd połączenia: {e}")

    return None, None, False, None, None, None

# --- STYLIZACJA CSS ---
st.markdown("""
<style>
.offer-row {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background-color: #1e2129;
    border: 1px solid #2d313e;
    border-radius: 8px;
    transition: background-color 0.2s ease;
}

.offer-row:hover {
    background-color: #2b303c;
}

.offer-info {
    display: flex;
    flex-direction: column;
    gap: 4px;
    max-width: 55%;
}

.offer-title {
    font-weight: 600;
    font-size: 15px;
    color: #ffffff;
    text-decoration: none;
}

.offer-title.inactive {
    text-decoration: line-through;
    color: #9ca3af;
}

.offer-title:hover {
    color: #ff4b4b;
}

.market-time-badge {
    font-size: 12px;
    color: #9ca3af;
}

.offer-price-box {
    display: flex;
    align-items: center;
    gap: 10px;
}

.current-price {
    font-weight: bold;
    font-size: 15px;
    color: #ffffff;
}

.price-delta-green {
    color: #22c55e;
    font-weight: bold;
    font-size: 13px;
    background: rgba(34, 197, 94, 0.1);
    padding: 2px 6px;
    border-radius: 4px;
}

.price-delta-red {
    color: #ef4444;
    font-weight: bold;
    font-size: 13px;
    background: rgba(239, 68, 68, 0.1);
    padding: 2px 6px;
    border-radius: 4px;
}

.price-delta-neutral {
    color: #9ca3af;
    font-weight: normal;
    font-size: 13px;
}

.status-badge-expired {
    color: #ef4444;
    font-weight: bold;
    font-size: 12px;
    background: rgba(239, 68, 68, 0.15);
    padding: 2px 8px;
    border-radius: 4px;
}

.hover-preview {
    display: none;
    position: absolute;
    left: 20px;
    top: 100%;
    z-index: 9999;
    background: #111827;
    border: 1px solid #374151;
    border-radius: 8px;
    padding: 6px;
    box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.5);
    width: 260px;
}

.hover-preview img {
    width: 100%;
    height: auto;
    border-radius: 6px;
    display: block;
}

.offer-row:hover .hover-preview {
    display: block;
}
</style>
""", unsafe_allow_html=True)

# --- WYŚWIETLANIE LOGO ---
col_logo1, col_logo2, col_logo3 = st.columns([1, 2, 1])
with col_logo2:
    if os.path.exists("logo.jpg"):
        st.image("logo.jpg", width="stretch")
    elif os.path.exists("logo.png"):
        st.image("logo.png", width="stretch")
    else:
        st.title("🚗 OTOMOTO śledzę ceny")

# --- CALLBACK DO CZYSZCZENIA POLA ---
def clear_url_input():
    st.session_state.url_input_key = ""

# --- INTERFEJS STREAMLIT ---
url_input = st.text_input(
    "Dodaj nowe ogłoszenie do śledzenia:",
    placeholder="tutaj wklej link z otomoto",
    key="url_input_key"
)

if st.button("Sprawdź i dodaj", type="primary", on_click=clear_url_input):
    if not url_input.strip():
        st.warning("Proszę podać poprawny URL.")
    else:
        with st.spinner("Pobieranie danych z Otomoto..."):
            nazwa, cena, aktywne, zdjecie, data_wystawienia, lokalizacja = sprawdz_i_pobierz_otomoto(url_input)

        if aktywne and cena is not None:
            save_price_entry(url_input, nazwa, cena, True, zdjecie, data_wystawienia, lokalizacja)
            st.success(f"Zapisano: {nazwa} – {cena:,.0f} PLN".replace(",", " "))
            st.rerun()
        else:
            save_price_entry(url_input, nazwa or "Wygasłe ogłoszenie", None, False, zdjecie, data_wystawienia, lokalizacja)
            st.warning("Ogłoszenie jest nieaktywne lub zostało usunięte. Zapisano status.")
            st.rerun()

st.divider()

col_head1, col_head2 = st.columns([2, 1])
with col_head1:
    st.subheader("📋 Śledzone oferty")
with col_head2:
    if st.button("🔄 Odśwież wszystkie", width="stretch"):
        summary_to_refresh = get_tracked_summary()
        if summary_to_refresh:
            progress_bar = st.progress(0)
            total = len(summary_to_refresh)
            
            for index, item in enumerate(summary_to_refresh):
                nazwa, cena, aktywne, zdjecie, data_wystawienia, lokalizacja = sprawdz_i_pobierz_otomoto(item['url'])
                
                title_to_save = nazwa if nazwa else item['title']
                img_to_save = zdjecie if zdjecie else item['image_url']
                pub_to_save = data_wystawienia if data_wystawienia else item['published_at']
                loc_to_save = lokalizacja if lokalizacja else item['location']
                
                save_price_entry(item['url'], title_to_save, cena, aktywne, img_to_save, pub_to_save, loc_to_save)
                progress_bar.progress((index + 1) / total)

            st.success("Zaktualizowano wszystkie oferty!")
            st.rerun()

summary_list = get_tracked_summary()

if not summary_list:
    st.info("Brak śledzonych ofert. Wklej link powyżej, aby dodać pierwsze auto.")
else:
    st.caption("Filtruj po marce:")
    
    if "selected_brand" not in st.session_state:
        st.session_state.selected_brand = None

    available_brands = sorted(list(set(item['brand'] for item in summary_list)))
    
    brand_cols = st.columns(len(available_brands) + 1)
    
    with brand_cols[0]:
        btn_type = "primary" if st.session_state.selected_brand is None else "secondary"
        if st.button("Wszystkie", type=btn_type, width="stretch"):
            st.session_state.selected_brand = None
            st.rerun()

    for idx, brand in enumerate(available_brands):
        with brand_cols[idx + 1]:
            btn_type = "primary" if st.session_state.selected_brand == brand else "secondary"
            if st.button(brand, type=btn_type, width="stretch"):
                if st.session_state.selected_brand == brand:
                    st.session_state.selected_brand = None
                else:
                    st.session_state.selected_brand = brand
                st.rerun()

    sort_option = st.selectbox(
        "Sortuj według:",
        [
            "Najnowsze na rynku",
            "Cena: Od najtańszych",
            "Cena: Od najdroższych",
            "Nazwa: A - Z"
        ]
    )

    filtered_list = summary_list
    if st.session_state.selected_brand:
        filtered_list = [item for item in summary_list if item['brand'] == st.session_state.selected_brand]

    if sort_option == "Najnowsze na rynku":
        filtered_list.sort(key=lambda x: x['days_on_market'])
    elif sort_option == "Cena: Od najtańszych":
        filtered_list.sort(key=lambda x: x['current_price'])
    elif sort_option == "Cena: Od najdroższych":
        filtered_list.sort(key=lambda x: x['current_price'], reverse=True)
    elif sort_option == "Nazwa: A - Z":
        filtered_list.sort(key=lambda x: x['title'].lower())

    st.write("")

    for item in filtered_list:
        col_item, col_delete = st.columns([12, 1])

        with col_item:
            days = item['days_on_market']
            if days == 0:
                time_str = "⏱️ Wystawiono dzisiaj"
            elif days == 1:
                time_str = "⏱️ 1 dzień na rynku"
            else:
                time_str = f"⏱️ {days} dni na rynku"

            loc_str = f" • 📍 {item['location']}" if item['location'] else ""
            sub_info_str = f"{time_str}{loc_str}"

            if item['is_active'] is False:
                title_class = "offer-title inactive"
                price_html = '<span class="status-badge-expired">Niedostępne / Wygaśnięte</span>'
                delta_html = ""
            else:
                title_class = "offer-title"
                price_html = f'<span class="current-price">{item["current_price"]:,.0f} PLN</span>'.replace(",", " ")
                
                diff = item['diff']
                if diff < 0:
                    delta_html = f'<span class="price-delta-green">{diff:,.0f} PLN</span>'.replace(",", " ")
                elif diff > 0:
                    delta_html = f'<span class="price-delta-red">+{diff:,.0f} PLN</span>'.replace(",", " ")
                else:
                    delta_html = '<span class="price-delta-neutral">0 PLN</span>'

            img_preview_html = ""
            if item['image_url']:
                img_preview_html = f'''
                <div class="hover-preview">
                    <img src="{item['image_url']}" alt="Zdjęcie podglądowe" />
                </div>
                '''

            st.markdown(
                f'''
                <div class="offer-row">
                    <div class="offer-info">
                        <a href="{item['url']}" target="_blank" class="{title_class}">{item['title']}</a>
                        <span class="market-time-badge">{sub_info_str}</span>
                    </div>
                    <div class="offer-price-box">
                        {price_html}
                        {delta_html}
                    </div>
                    {img_preview_html}
                </div>
                ''',
                unsafe_allow_html=True
            )

        with col_delete:
            if st.button("🗑️", key=f"del_{item['url']}", help="Usuń ofertę z listy"):
                delete_offer(item['url'])
                st.rerun()
