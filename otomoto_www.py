import json
import os
import re
import warnings
from datetime import datetime
import pandas as pd
import psycopg2
import requests
import streamlit as st

# --- KONFIGURACJA STRONY ---
st.set_page_config(
    page_title="Otomoto Price Tracker", 
    page_icon="🚗", 
    layout="wide"
)

# --- MAPOWANIE MIESIĘCY ---
MONTHS_PL = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "października": 10, "listopada": 11, "grudnia": 12
}

# --- BAZA DANYCH (Supabase / PostgreSQL) ---
def get_db_connection():
    try:
        conn = psycopg2.connect(st.secrets["DATABASE_URL"])
        return conn
    except Exception as e:
        st.error(f"Błąd połączenia z bazą Supabase: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS price_history (
            id SERIAL PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT,
            price NUMERIC,
            is_active INT DEFAULT 1,
            timestamp TIMESTAMP NOT NULL,
            image_url TEXT,
            published_at TEXT,
            location TEXT,
            year INT,
            mileage TEXT,
            engine TEXT,
            fuel TEXT
        );
    ''')
    
    for col in ["title TEXT", "is_active INT DEFAULT 1", "published_at TEXT", "location TEXT", "year INT", "mileage TEXT", "engine TEXT", "fuel TEXT"]:
        try:
            c.execute(f"ALTER TABLE price_history ADD COLUMN IF NOT EXISTS {col};")
        except Exception:
            pass

    conn.commit()
    c.close()
    conn.close()

def save_price_entry(url, title, price, is_active, image_url, published_at, location, year, mileage, engine, fuel):
    conn = get_db_connection()
    if not conn:
        return
    c = conn.cursor()
    now = datetime.now()
    active_int = 1 if is_active else 0
    price_to_save = float(price) if price is not None else None

    c.execute(
        """
        INSERT INTO price_history (url, title, price, is_active, timestamp, image_url, published_at, location, year, mileage, engine, fuel) 
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (url, title, price_to_save, active_int, now, image_url, published_at, location, year, mileage, engine, fuel)
    )
    conn.commit()
    c.close()
    conn.close()

def delete_offer(url):
    conn = get_db_connection()
    if not conn:
        return
    c = conn.cursor()
    c.execute("DELETE FROM price_history WHERE url = %s", (url,))
    conn.commit()
    c.close()
    conn.close()

def parse_publication_date(date_str):
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
    if not title or title == "Ogłoszenie Otomoto":
        return "Inne"
    parts = title.strip().split()
    return parts[0].capitalize() if parts else "Inne"

def clean_location(raw_loc):
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
    conn = get_db_connection()
    if not conn:
        return []
        
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = pd.read_sql_query(
                "SELECT url, title, price, is_active, timestamp, image_url, published_at, location, year, mileage, engine, fuel FROM price_history ORDER BY timestamp ASC",
                conn
            )
    except Exception as e:
        st.error(f"Błąd odczytu z bazy: {e}")
        return []
    finally:
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
            first_seen_dt = pd.to_datetime(first_entry['timestamp'])
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
            'year': latest_entry['year'] if pd.notna(latest_entry['year']) else None,
            'mileage': latest_entry['mileage'] if pd.notna(latest_entry['mileage']) else None,
            'engine': latest_entry['engine'] if pd.notna(latest_entry['engine']) else None,
            'fuel': latest_entry['fuel'] if pd.notna(latest_entry['fuel']) else None,
            'last_updated': latest_entry['timestamp']
        })

    return summary

init_db()

# --- SCRAPER ---
def sprawdz_i_pobierz_otomoto(url):
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
            return None, None, False, None, None, None, None, None, None, None

        html = response.text

        if "Ogłoszenie jest nieaktualne" in html or "To ogłoszenie nie jest już dostępne" in html:
            return None, None, False, None, None, None, None, None, None, None

        title = None
        cena = None
        url_zdjecia = None
        published_at = None
        location = None
        year = None
        mileage = None
        engine = None
        fuel = None

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

                params = ad_data.get("params", [])
                engine_capacity = None
                engine_power = None

                for p in params:
                    key = p.get("key")
                    value = p.get("value")
                    display_value = p.get("displayValue")

                    if key == "year":
                        try:
                            year = int(value)
                        except Exception:
                            pass
                    elif key == "mileage":
                        mileage = f"{int(value):,} km".replace(",", " ") if value and value.isdigit() else display_value
                    elif key == "fuel_type":
                        fuel = display_value
                    elif key == "engine_capacity":
                        engine_capacity = f"{int(value)} cm³" if value and value.isdigit() else display_value
                    elif key == "engine_power":
                        engine_power = f"{int(value)} KM" if value and value.isdigit() else display_value

                if engine_capacity and engine_power:
                    engine = f"{engine_capacity} • {engine_power}"
                elif engine_capacity:
                    engine = engine_capacity
                elif engine_power:
                    engine = engine_power

        if not location:
            loc_matches = re.findall(r'<p[^>]*class="[^"]*ooa-889rdv[^"]*"[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
            for loc_raw in loc_matches:
                cand_loc = clean_location(loc_raw)
                if cand_loc:
                    location = cand_loc
                    break

        if not published_at:
            date_match = re.search(r'<p[^>]*class="[^"]*text-foreground-secondary[^"]*"[^>]*>(\d{1,2}\s+[a-złóężąśćźń]+\s+\d{4}[^<]*)</p>', html, re.IGNORECASE)
            if date_match:
                published_at = date_match.group(1).strip()

        if not title:
            h1_match = re.search(r'<h1[^>]*class="[^"]*offer-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL | re.IGNORECASE)
            if h1_match:
                title = re.sub(r'<[^>]+>', '', h1_match.group(1)).strip()

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
            return final_title, cena, True, url_zdjecia, published_at, location, year, mileage, engine, fuel

    except Exception as e:
        st.error(f"Błąd połączenia: {e}")

    return None, None, False, None, None, None, None, None, None, None

# --- STYLIZACJA KAFELKOWA ---
st.markdown("""
<style>
.otomoto-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 12px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.05);
}

.otomoto-card-img {
    width: 100%;
    height: 180px;
    object-fit: cover;
    display: block;
}

.otomoto-card-body {
    padding: 14px;
    color: #1e293b;
}

.otomoto-price-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 6px;
}

.otomoto-price {
    font-size: 20px;
    font-weight: 800;
    color: #0f172a;
}

.otomoto-title {
    font-size: 15px;
    font-weight: 700;
    color: #0f172a !important;
    text-decoration: none !important;
    margin-bottom: 4px;
    display: block;
    line-height: 1.3;
}

.otomoto-title:hover {
    color: #0071CE !important;
}

.otomoto-engine {
    font-size: 12px;
    color: #64748b;
    margin-bottom: 8px;
}

.otomoto-specs {
    font-size: 13px;
    color: #334155;
    margin-bottom: 8px;
    border-top: 1px solid #f1f5f9;
    padding-top: 6px;
}

.otomoto-footer {
    font-size: 12px;
    color: #64748b;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-top: 1px solid #f1f5f9;
    padding-top: 6px;
}

.price-delta-green {
    color: #16a34a;
    font-weight: bold;
    font-size: 12px;
    background: #dcfce7;
    padding: 2px 6px;
    border-radius: 4px;
}

.price-delta-red {
    color: #dc2626;
    font-weight: bold;
    font-size: 12px;
    background: #fee2e2;
    padding: 2px 6px;
    border-radius: 4px;
}

div[data-testid="stForm"] {
    border: none;
    padding: 0;
}
</style>
""", unsafe_allow_html=True)

# --- HEADER LOGO ---
col_logo1, col_logo2, col_logo3 = st.columns([1, 2, 1])
with col_logo2:
    if os.path.exists("logo.jpg"):
        st.image("logo.jpg", width="stretch")
    elif os.path.exists("logo.png"):
        st.image("logo.png", width="stretch")
    else:
        st.title("🚗 OTOMOTO śledzę ceny")

# --- FORMULARZ DODAWANIA ---
with st.form("add_offer_form", clear_on_submit=True):
    url_input = st.text_input(
        "Dodaj nowe ogłoszenie do śledzenia:",
        placeholder="tutaj wklej link z otomoto"
    )
    submit_button = st.form_submit_button("Sprawdź i dodaj", type="primary")

if submit_button:
    if not url_input.strip():
        st.warning("Proszę podać poprawny URL.")
    else:
        with st.spinner("Pobieranie danych z Otomoto..."):
            nazwa, cena, aktywne, zdjecie, data_wystawienia, lokalizacja, rok, przebieg, silnik, paliwo = sprawdz_i_pobierz_otomoto(url_input)

        if aktywne and cena is not None:
            save_price_entry(url_input, nazwa, cena, True, zdjecie, data_wystawienia, lokalizacja, rok, przebieg, silnik, paliwo)
            st.success(f"Zapisano: {nazwa} – {cena:,.0f} PLN".replace(",", " "))
            st.rerun()
        else:
            save_price_entry(url_input, nazwa or "Wygasłe ogłoszenie", None, False, zdjecie, data_wystawienia, lokalizacja, rok, przebieg, silnik, paliwo)
            st.warning("Ogłoszenie jest nieaktywne lub zostało usunięte. Zapisano status.")
            st.rerun()

st.divider()

col_head1, col_head2 = st.columns([3, 1])
with col_head1:
    st.subheader("📋 Śledzone oferty")
with col_head2:
    if st.button("🔄 Odśwież wszystkie", width="stretch"):
        summary_to_refresh = get_tracked_summary()
        if summary_to_refresh:
            progress_bar = st.progress(0)
            total = len(summary_to_refresh)
            
            for index, item in enumerate(summary_to_refresh):
                nazwa, cena, aktywne, zdjecie, data_wystawienia, lokalizacja, rok, przebieg, silnik, paliwo = sprawdz_i_pobierz_otomoto(item['url'])
                
                title_to_save = nazwa if nazwa else item['title']
                img_to_save = zdjecie if zdjecie else item['image_url']
                pub_to_save = data_wystawienia if data_wystawienia else item['published_at']
                loc_to_save = lokalizacja if lokalizacja else item['location']
                
                save_price_entry(item['url'], title_to_save, cena, aktywne, img_to_save, pub_to_save, loc_to_save, rok, przebieg, silnik, paliwo)
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
        ["Najnowsze na rynku", "Cena: Od najtańszych", "Cena: Od najdroższych", "Nazwa: A - Z"]
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

    # --- SIATKA KAFELKOWA (3 KOLUMNY) ---
    grid_cols = st.columns(3)

    for index, item in enumerate(filtered_list):
        col = grid_cols[index % 3]

        with col:
            if not item['is_active']:
                price_html = '<span style="color: #dc2626; font-size: 16px; font-weight: bold;">Niedostępne</span>'
                delta_html = ""
            else:
                price_html = f'<span class="otomoto-price">{item["current_price"]:,.0f} PLN</span>'.replace(",", " ")
                diff = item['diff']
                if diff < 0:
                    delta_html = f'<span class="price-delta-green">{diff:,.0f} PLN</span>'.replace(",", " ")
                elif diff > 0:
                    delta_html = f'<span class="price-delta-red">+{diff:,.0f} PLN</span>'.replace(",", " ")
                else:
                    delta_html = ""

            img_url = item['image_url'] or "https://via.placeholder.com/400x250?text=Brak+Zdjęcia"
            engine_str = item['engine'] if item['engine'] else ""
            mileage_str = f"🛣️ {item['mileage']}" if item['mileage'] else ""
            fuel_str = f"⛽ {item['fuel']}" if item['fuel'] else ""
            year_str = f"📅 {item['year']}" if item['year'] else ""
            location_str = item['location'] if item['location'] else "Brak lokalizacji"
            
            days = item['days_on_market']
            time_str = "⏱️ Dzisiaj" if days == 0 else (f"⏱️ 1 dzień" if days == 1 else f"⏱️ {days} dni")

            card_html = (
                f'<div class="otomoto-card">'
                f'<img src="{img_url}" class="otomoto-card-img" />'
                f'<div class="otomoto-card-body">'
                f'<div class="otomoto-price-row">{price_html}{delta_html}</div>'
                f'<a href="{item["url"]}" target="_blank" class="otomoto-title">{item["title"]}</a>'
                f'<div class="otomoto-engine">{engine_str}</div>'
                f'<div class="otomoto-specs"><div>{mileage_str}</div><div>{fuel_str} &nbsp; {year_str}</div></div>'
                f'<div class="otomoto-footer"><span>📍 {location_str}</span><span>{time_str}</span></div>'
                f'</div>'
                f'</div>'
            )

            st.markdown(card_html, unsafe_allow_html=True)

            if st.button("🗑️ Usuń z listy", key=f"del_{item['url']}", width="stretch"):
                delete_offer(item['url'])
                st.rerun()
            st.write("")
