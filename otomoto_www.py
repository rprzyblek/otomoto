import json
import os
from datetime import datetime
import streamlit as st
import pandas as pd

DB_FILE = "historia_cen_web.json"

def wczytaj_baze():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def zapisz_baze(dane):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(dane, f, indent=4, ensure_ascii=False)

# Konfiguracja układy strony WWW
st.set_page_config(page_title="Price Tracker WWW", page_icon="📈", layout="wide")

st.title("📈 Price Tracker WWW")
st.caption("Aplikacja webowa do monitorowania cen w Pythonie")

# --- PANEL BOCZNY (Sidebar) ---
st.sidebar.header("➕ Dodaj nowy produkt")
nazwa = st.sidebar.text_input("Nazwa / Model")
url = st.sidebar.text_input("Link do oferty")
cena_startowa = st.sidebar.number_input("Cena początkowa (PLN)", min_value=0.0, step=100.0)

if st.sidebar.button("Dodaj do bazy", use_container_width=True):
    if nazwa and url:
        baza = wczytaj_baze()
        dzis = datetime.now().strftime("%Y-%m-%d")
        
        baza[nazwa] = {
            "url": url,
            "aktywny": True,
            "historia": {dzis: cena_startowa}
        }
        zapisz_baze(baza)
        st.sidebar.success(f"Dodano: {nazwa}")
        st.rerun()
    else:
        st.sidebar.error("Wypełnij nazwę oraz link!")

# --- GŁÓWNY PANEL ---
baza = wczytaj_baze()

if not baza:
    st.info("Baza danych jest pusta. Dodaj pierwszy produkt w panelu bocznym po lewej stronie.")
else:
    wybrany_produkt = st.selectbox("Wybierz śledzony pojazd / przedmiot:", list(sorted(baza.keys())))

    if wybrany_produkt:
        dane = baza[wybrany_produkt]
        historia = dane["historia"]

        # Przygotowanie danych do wykresu w Pandas
        df = pd.DataFrame(list(historia.items()), columns=["Data", "Cena"])
        df["Data"] = pd.to_datetime(df["Data"])
        df = df.sort_values("Data")

        ostatnia_cena = df["Cena"].iloc[-1]
        pierwsza_cena = df["Cena"].iloc[0]
        roznica = ostatnia_cena - pierwsza_cena

        # KPI Metrics
        col1, col2, col3 = st.columns(3)
        col1.metric("Aktualna cena", f"{ostatnia_cena:,.0f} PLN".replace(",", " "))
        col2.metric("Cena początkowa", f"{pierwsza_cena:,.0f} PLN".replace(",", " "))
        col3.metric(
            "Zmiana ceny", 
            f"{roznica:,.0f} PLN".replace(",", " "), 
            delta=f"{roznica:,.0f} PLN", 
            delta_color="inverse"
        )

        st.divider()

        # Interaktywny wykres liniowy
        st.subheader("📉 Wykres historii ceny")
        st.line_chart(df.set_index("Data")["Cena"])

        # Link zewnętrzny i tabela historii
        st.markdown(f"[🔗 Otwórz oryginalne ogłoszenie]({dane['url']})")
        
        with st.expander("Pokaż surowe dane w tabeli"):
            st.dataframe(df, use_container_width=True)

        # Przycisk usuwania
        if st.button("🗑️ Usuń ten produkt z bazy", type="secondary"):
            del baza[wybrany_produkt]
            zapisz_baze(baza)
            st.success("Usunięto z bazy!")
            st.rerun()