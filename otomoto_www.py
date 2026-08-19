import json
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

# --- BAZA DANYCH (SQLite) ---
DB_NAME = "price_tracker.db"

def init_db():
    """Inicjalizacja tabeli w bazie danych jeśli nie istnieje."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            price REAL NOT NULL,
            timestamp DATETIME NOT NULL,
            image_url TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_price_entry(url, title, price, image_url):
    """Zapisuje nowy pomiar ceny do bazy danych."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO price_history (url, title, price, timestamp, image_url) VALUES (?, ?, ?, ?, ?)",
        (url, title, price, now, image_url)
    )
    conn.commit()
    conn.close()

def get_tracked_summary():
    """Pobiera zestawienie wszystkich śledzonych ofert z wyliczeniem różnicy ceny (+/-)."""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(
        "SELECT url, title, price, timestamp, image_url FROM price_history ORDER BY timestamp ASC",
        conn
    )
    conn.close()

    if df.empty:
        return []

    summary = []
    grouped = df.groupby('url')

    for url, group in grouped:
        first_entry = group.iloc[0]
        latest_entry = group.iloc[-1]

        title = latest_entry['title'] or "Ogłoszenie Otomoto"
        current_price = latest_entry['price']
        first_price = first_entry['price']
        diff = current_price - first_price
        image_url = latest_entry['image_url']

        summary.append({
            'url': url,
            'title': title,
            'current_price': current_price,
            'diff': diff,
            'image_url': image_url,
            'last_updated': latest_entry['timestamp']
        })

    # Sortowanie od najnowszych
    summary.reverse()
    return summary

init_db()

# --- SCRAPER ---
def sprawdz_i_pobierz_otomoto(url):
    """Pobiera nazwę, aktualną cenę i zdjęcie z Otomoto."""
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
            return None, None, False, None

        html = response.text

        if "Ogłoszenie jest nieaktualne" in html or "To ogłoszenie nie jest już dostępne" in html:
            return None, None, False, None

        # 1. Wyciąganie JSON z __NEXT_DATA__
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if match:
            json_data = json.loads(match.group(1))
            ad_data = json_data.get("props", {}).get("pageProps", {}).get("ad", {})

            if ad_data:
                title = ad_data.get("title") or "Ogłoszenie Otomoto"
                cena = float(ad_data["price"]["value"])
                photos = ad_data.get("photos", [])
                url_zdjecia = None

                if photos:
                    url_zdjecia = photos[0].get("url") or photos[0].get("medium")

                return title, cena, True, url_zdjecia

        # 2. Rezerwowy zapis z metatagów
        title_match = re.search(r'<meta property="og:title" content="(.*?)"', html)
        title_alt = title_match.group(1) if title_match else "Ogłoszenie Otomoto"

        price_match = re.search(r"(\d[\d\s]+)\s*PLN", html)
        cena_alt = None
        if price_match:
            clean = "".join(re.findall(r"\d+", price_match.group(1)))
            if clean:
                cena_alt = float(clean)

        og_image_match = re.search(r'<meta property="og:image" content="(.*?)"', html)
        url_zdjecia_alt = og_image_match.group(1) if og_image_match else None

        if cena_alt is not None:
            return title_alt, cena_alt, True, url_zdjecia_alt

    except Exception as e:
        st.error(f"Błąd połączenia: {e}")

    return None, None, False, None

# --- STYLIZACJA CSS (Podgląd zdjęcia po najechaniu myszką) ---
st.markdown("""
<style>
.offer-row {
    position: relative;
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    margin-bottom: 10px;
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
}

.offer-title {
    font-weight: 600;
    font-size: 15px;
    color: #ffffff;
    text-decoration: none;
}

.offer-title:hover {
    color: #ff4b4b;
    text-decoration: underline;
}

.offer-price-box {
    display: flex;
    align-items: center;
    gap: 12px;
}

.current-price {
    font-weight: bold;
    font-size: 16px;
    color: #ffffff;
}

.price-delta-green {
    color: #22c55e;
    font-weight: bold;
    font-size: 14px;
    background: rgba(34, 197, 94, 0.1);
    padding: 2px 8px;
    border-radius: 4px;
}

.price-delta-red {
    color: #ef4444;
    font-weight: bold;
    font-size: 14px;
    background: rgba(239, 68, 68, 0.1);
    padding: 2px 8px;
    border-radius: 4px;
}

.price-delta-neutral {
    color: #9ca3af;
    font-weight: normal;
    font-size: 14px;
}

/* Tooltip / Popup ze zdjęciem auta */
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

# --- INTERFEJS STREAMLIT ---
st.title("🚗 Śledzenie Cen Otomoto")

url_input = st.text_input(
    "Dodaj nowe ogłoszenie do śledzenia:",
    placeholder="https://www.otomoto.pl/osobowe/oferta/...",
)

if st.button("Sprawdź i dodaj/zaktualizuj", type="primary"):
    if not url_input.strip():
        st.warning("Proszę podać poprawny URL.")
    else:
        with st.spinner("Pobieranie danych z Otomoto..."):
            nazwa, cena, aktywne, zdjecie = sprawdz_i_pobierz_otomoto(url_input)

        if aktywne and cena is not None:
            save_price_entry(url_input, nazwa, cena, zdjecie)
            st.success(f"Zapisano: {nazwa} – {cena:,.0f} PLN".replace(",", " "))
            st.rerun()
        else:
            st.error("Ogłoszenie jest nieaktywne, usunięte lub podany link jest nieprawidłowy.")

st.divider()
st.subheader("📋 Śledzone oferty")

summary_list = get_tracked_summary()

if not summary_list:
    st.info("Brak śledzonych ofert. Wklej link powyżej, aby dodać pierwsze auto.")
else:
    for item in summary_list:
        # Formatowanie zmiany ceny (+/-)
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
                    <a href="{item['url']}" target="_blank" class="offer-title">{item['title']}</a>
                </div>
                <div class="offer-price-box">
                    <span class="current-price">{item['current_price']:,.0f} PLN</span>
                    {delta_html}
                </div>
                {img_preview_html}
            </div>
            '''.replace(",", " "),
            unsafe_allow_html=True
        )
