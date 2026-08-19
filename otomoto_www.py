import json
import re
import requests
import streamlit as st

# Config strony Streamlit
st.set_page_config(
    page_title="Otomoto Price Tracker", page_icon="🚗", layout="centered"
)


def sprawdz_i_pobierz_otomoto(url):
    """Szybki i lekki scraper Otomoto pod Streamlit Cloud (bez Playwright).

    Wyciąga dane bezpośrednio z JSON __NEXT_DATA__. Zwraca: (cena, czy_aktywne,
    url_zdjecia)
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "pl,en-US;q=0.7,en;q=0.3",
        "Cache-Control": "no-cache",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code in [403, 404, 410]:
            return None, False, None

        html = response.text

        # Sprawdzenie nieaktywności ogłoszenia
        if (
            "Ogłoszenie jest nieaktualne" in html
            or "To ogłoszenie nie jest już dostępne" in html
        ):
            return None, False, None

        # Wyciąganie JSON z __NEXT_DATA__
        match = re.search(
            r'<script id="__NEXT_DATA__"'
            r' type="application/json">(.*?)</script>',
            html,
        )
        if match:
            json_data = json.loads(match.group(1))
            ad_data = (
                json_data.get("props", {})
                .get("pageProps", {})
                .get("ad", {})
            )

            if ad_data:
                cena = float(ad_data["price"]["value"])
                photos = ad_data.get("photos", [])
                url_zdjecia = None

                if photos:
                    url_zdjecia = photos[0].get("url") or photos[0].get(
                        "medium"
                    )

                return cena, True, url_zdjecia

        # Rezerwowy zapis z OpenGraph / Title
        title_match = re.search(r"(\d[\d\s]+)\s*PLN", html)
        cena_alt = None
        if title_match:
            clean = "".join(re.findall(r"\d+", title_match.group(1)))
            if clean:
                cena_alt = float(clean)

        og_image_match = re.search(
            r'<meta property="og:image" content="(.*?)"', html
        )
        url_zdjecia_alt = og_image_match.group(1) if og_image_match else None

        if cena_alt is not None:
            return cena_alt, True, url_zdjecia_alt

    except Exception as e:
        st.error(f"Błąd połączenia: {e}")

    return None, False, None


# --- INTERFEJS STREAMLIT ---
st.title("🚗 Śledzenie Cen Otomoto")
st.write("Wklej link do ogłoszenia, aby sprawdzić aktualną cenę i status.")

url_input = st.text_input(
    "URL ogłoszenia Otomoto:",
    placeholder="https://www.otomoto.pl/osobowe/oferta/...",
)

if st.button("Sprawdź ogłoszenie", type="primary"):
    if not url_input.strip():
        st.warning("Proszę podać poprawny URL.")
    else:
        with st.spinner("Pobieranie danych z Otomoto..."):
            cena, aktywne, zdjecie = sprawdz_i_pobierz_otomoto(url_input)

        if aktywne and cena is not None:
            st.success("Ogłoszenie jest aktywne!")

            col1, col2 = st.columns([1, 2])

            with col1:
                if zdjecie:
                    st.image(zdjecie, use_container_width=True)
                else:
                    st.info("Brak zdjęcia")

            with col2:
                st.metric(label="Aktualna cena", value=f"{cena:,.0f} PLN".replace(",", " "))
        else:
            st.error("Ogłoszenie jest nieaktywne, usunięte lub podany link jest nieprawidłowy.")
