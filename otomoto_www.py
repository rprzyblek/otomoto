import sqlite3
from datetime import datetime
import json
import re
import requests
import pandas as pd
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
            price REAL NOT NULL,
            timestamp DATETIME NOT NULL,
            image_url TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_price_entry(url, price, image_url):
    """Zapisuje nowy pomiar ceny do bazy danych."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO price_history (url, price, timestamp, image_url) VALUES (?, ?, ?, ?)",
        (url, price, now, image_url)
    )
    conn.commit()
    conn.close()

def get_price_history(url):
    """Pobiera historię cen dla danego URL w postaci DataFrame."""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query(
        "SELECT timestamp, price FROM price_history WHERE url = ? ORDER BY timestamp ASC",
        conn,
        params=(url,)
    )
    conn.close()
    if not df.empty:
        df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df

def get_all_tracked_urls():
    """Pobiera unikalną listę śledzonych adresów URL."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT DISTINCT url FROM price_history ORDER BY id DESC")
    urls = [row[0] for row in c.fetchall()]
    conn.close()
    return urls

# Inicjalizacja bazy danych przy starcie
init_db()

# --- SCRAPER ---
def sprawdz_i_pobierz_otomoto(url):
    """Pobiera aktualną cenę i zdjęcie z Otomoto."""
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
            return None, False, None

        html = response.text

        if "Ogłoszenie jest nieaktualne" in html or "To ogłoszenie nie jest już dostępne" in html:
            return None, False, None

        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if match:
            json_data = json.loads(match.group(1))
            ad_data = json_data.get("props", {}).get("pageProps", {}).get("ad", {})

            if ad_data:
                cena = float(ad_data["price"]["value"])
                photos = ad_data.get("photos", [])
                url_zdjecia = None

                if photos:
                    url_zdjecia = photos[0].get("url") or photos[0].get("medium")

                return cena, True, url_zdjecia

        # Rezerwowy zapis
        title_match = re.search(r"(\d[\d\s]+)\s*PLN", html)
        cena_alt = None
        if title_match:
            clean = "".join(re.findall(r"\d+", title_match.group(1)))
            if clean:
                cena_alt = float(clean)

        og_image_match = re.search(r'<meta property="og:image" content="(.*?)"', html)
        url_zdjecia_alt = og_image_match.group(1) if og_image_match else None

        if cena_alt is not None:
            return cena_alt, True, url_zdjecia_alt

    except Exception as e:
        st.error(f"Błąd połączenia: {e}")

    return None, False, None


# --- INTERFEJS STREAMLIT ---
st.title("🚗 Śledzenie Cen Otomoto")

# Szybki wybór z historii
tracked_urls = get_all_tracked_urls()
selected_from_history = None

if tracked_urls:
    with st.expander("📂 Wybierz z ostatnio śledzonych ofert"):
        selected_from_history = st.selectbox("Szybki wybór URL:", ["-- Wybierz z listy --"] + tracked_urls)

# Pole tekstowe do podania URL
default_url = selected_from_history if selected_from_history and selected_from_history != "-- Wybierz z listy --" else ""
url_input = st.text_input(
    "URL ogłoszenia Otomoto:",
    value=default_url,
    placeholder="https://www.otomoto.pl/osobowe/oferta/...",
)

if st.button("Sprawdź i Zapisz Cenę", type="primary"):
    if not url_input.strip():
        st.warning("Proszę podać poprawny URL.")
    else:
        with st.spinner("Pobieranie danych z Otomoto..."):
            cena, aktywne, zdjecie = sprawdz_i_pobierz_otomoto(url_input)

        if aktywne and cena is not None:
            # Zapis do bazy danych
            save_price_entry(url_input, cena, zdjecie)
            st.success("Pomyślnie pobrano dane i zaktualizowano historię!")

            col1, col2 = st.columns([1, 2])

            # Col 1: Klikalne zdjęcie przekierowujące do oferty
            with col1:
                if zdjecie:
                    st.markdown(
                        f"""
                        <a href="{url_input}" target="_blank" title="Kliknij, aby przejść do ogłoszenia">
                            <img src="{zdjecie}" style="width: 100%; border-radius: 10px; transition: transform 0.2s;" onmouseover="this.style.transform='scale(1.03)'" onmouseout="this.style.transform='scale(1)'"/>
                        </a>
                        <p style="text-align: center; font-size: 12px; color: #888; margin-top: 5px;">👆 Kliknij zdjęcie, aby otworzyć ofertę</p>
                        """,
                        unsafe_allow_html=True
                    )
                else:
                    st.info("Brak zdjęcia")

            # Col 2: Aktualna cena i statystyki
            with col2:
                st.metric(label="Aktualna cena", value=f"{cena:,.0f} PLN".replace(",", " "))
                
                history_df = get_price_history(url_input)
                if not history_df.empty and len(history_df) > 1:
                    first_price = history_df.iloc[0]['price']
                    diff = cena - first_price
                    st.metric(
                        label="Zmiana od pierwszego pomiaru", 
                        value=f"{diff:,.0f} PLN".replace(",", " "),
                        delta=f"{diff:,.0f} PLN".replace(",", " "),
                        delta_color="inverse" # spadek ceny jest na zielono
                    )

            # Wykres historii cen
            st.subheader("📈 Historia cen")
            history_df = get_price_history(url_input)

            if not history_df.empty:
                chart_data = history_df.set_index('timestamp')['price']
                st.line_chart(chart_data)
            else:
                st.info("Brak historii dla tego ogłoszenia. To pierwsze sprawdzenie.")

        else:
            st.error("Ogłoszenie jest nieaktywne, usunięte lub podany link jest nieprawidłowy.")
