import re
import json
import urllib.request
from playwright.sync_api import sync_playwright

def sprawdz_i_pobierz_otomoto(url):
    """
    Optymalizowany pod serwery chmurowe scraper Otomoto.
    Zwraca: (cena, czy_aktywne, url_zdjecia)
    """
    try:
        with sync_playwright() as p:
            # Flagi wymagane na serwerach chmurowych (Linux/Docker) do ominięcia Cloudflare
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars"
                ]
            )
            
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                locale="pl-PL",
                viewport={"width": 1920, "height": 1080}
            )
            
            # Maskowanie faktu, że to automatyzacja (ukrycie webdrivera)
            page = context.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            response = page.goto(url, wait_until="domcontentloaded", timeout=40000)
            
            if response is None or response.status in [403, 404, 410]:
                browser.close()
                return None, False, None
                
            page.wait_for_timeout(3000)
            html_content = page.content()
            
            # Sprawdzenie nieaktywności
            if "Ogłoszenie jest nieaktualne" in html_content or "To ogłoszenie nie jest już dostępne" in html_content:
                browser.close()
                return None, False, None

            cena = None
            url_zdjecia = None

            # 1. Odczyt ceny z tagu __NEXT_DATA__ (najbardziej odporne na serwerach)
            try:
                next_data = page.locator('script#__NEXT_DATA__')
                if next_data.count() > 0:
                    json_raw = next_data.inner_text()
                    data = json.loads(json_raw)
                    ad_data = data['props']['pageProps']['ad']
                    cena = float(ad_data['price']['value'])
                    
                    photos = ad_data.get('photos', [])
                    if photos:
                        url_zdjecia = photos[0].get('url') or photos[0].get('medium')
            except Exception:
                pass

            # 2. Rezerwowe pobieranie ceny z tytułu strony lub nagłówków
            if cena is None:
                title_text = page.title()
                match = re.search(r'(\d[\d\s]+)\s*PLN', title_text)
                if match:
                    clean = ''.join(re.findall(r'\d+', match.group(1)))
                    if clean:
                        cena = float(clean)

            # 3. Rezerwowe pobieranie zdjęcia z OpenGraph
            if not url_zdjecia:
                try:
                    og_image = page.locator('meta[property="og:image"]')
                    if og_image.count() > 0:
                        url_zdjecia = og_image.first.get_attribute("content")
                except Exception:
                    pass

            browser.close()
            
            if cena is not None:
                return cena, True, url_zdjecia

    except Exception as e:
        print(f"Błąd Playwright: {e}")
        
    return None, False, None
