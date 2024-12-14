import sqlite3
from contextlib import contextmanager

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
from requests.exceptions import ConnectTimeout
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException, TimeoutException

max_attempts = 5

@contextmanager
def db_connection():
    conn = sqlite3.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        conn.close()

def FindFueltypeId(drivstoff):
    fuelId = None
    
    with db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM fueltypes WHERE type = ?", (drivstoff,))
        car = c.fetchone()
        
        if car is not None:
            fuelId = car[0]
        
        return fuelId

def does_car_id_exist(car_id):
    carId = None
    
    with db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT car_id FROM cars WHERE car_id = ? LIMIT 1", (car_id,))
        car = c.fetchone()

        if car is not None:
            carId = car[0]
        return carId

def insert_car(cursor, car, timestamp):
    try:
        cursor.execute("""
            INSERT INTO cars (car_id, make, model, year, km, gear, fuelTypeId, vin, timestamp, freeTextModel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (car['carId'], car['make'], car['model'], car['year'], car['km'], car['gear'], car['fuelTypeId'], car['VIN'], timestamp, car['freeTextModel']))
    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"En bil med ID {car['carId']} eksisterer allerede i databasen.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

def insert_price(cursor, car_id, price, timestamp):
    cursor.execute("""
        INSERT INTO prices (car_id, price, timestamp)
        VALUES (?, ?, ?)
    """, (car_id, price, timestamp))

def handle_existing_car(cursor, car, timestamp):
    if car['price'] == 9:
        cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car['carId'],))
        car_exists = cursor.fetchone()
        if car_exists is None:
            cursor.execute("INSERT INTO inactivecars SELECT * FROM cars WHERE car_id = ?", (car['carId'],))
            cursor.execute("DELETE FROM cars WHERE car_id = ?", (car['carId'],))
    else:
        cursor.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car['carId'],))
        price_found = cursor.fetchone()
        if price_found:
            if int(car['price']) != int(price_found[0]):
                insert_price(cursor, car['carId'], car['price'], timestamp)
        else:
            insert_price(cursor, car['carId'], car['price'], timestamp)

def insert_car_and_price(carData):
    with db_connection() as conn:
        c = conn.cursor()
        now = c.execute("SELECT datetime('now', 'localtime')").fetchone()[0]

        for car in carData:
            existing_car_id = does_car_id_exist(car['carId'])
            if existing_car_id is None and car['price'] != 9:
                insert_car(c, car, now)
                insert_price(c, car['carId'], car['price'], now)
            else:
                handle_existing_car(c, car, now)
                if car['price'] is None:
                    print(f"{car['carId']} price is None")

        conn.commit()

def split_car_name(name):
    # Liste med toords-bilmerker
    two_word_brands = ['Land Rover', 'Alfa Romeo', 'Rolls Royce', 'Mercedes-Benz', 'Aston Martin', 'Austin Healey', 'Mitsubishi Motors', 'General Motors']
    
    # Sjekk for toords-bilmerker
    for brand in two_word_brands:
        if brand in name:
            return brand, name.replace(brand, '').strip()

    # Hvis det bare er ett ord i navnet, returner det som merket og modellen som en tom streng.
    if ' ' not in name:
        return name, ''

    # Hvis ingen toords-bilmerker finnes, deler vi navnet ved det første mellomrommet for å få merket og modellen.
    brand, model = name.split(' ', 1)
    return brand, model

def ExtractCarData(carData, car_tags, model):
    checkCarIdForDups = set()
    
    for tag in car_tags:
        # Henter bilens ID
        car_link_tag = tag.find('a', class_='sf-search-ad-link')
        car_id = car_link_tag.get('id')
        
        # Sjekk for dups
        if car_id in checkCarIdForDups:
            continue
        else:
            checkCarIdForDups.add(car_id)
        
        # Henter merke og navnet på bilen
        make, freeTextModel = split_car_name(car_link_tag.text.strip())

        # Henter extendet data
        vin, gear, fuelTypeId = get_extended_car_data(car_id)
        
        # Henter pris, kilometer og år
        price_div = tag.select_one('div.mb-8.flex.justify-between.whitespace-nowrap.font-bold')
        if price_div:
            km = 0
            price = 0
            year = 9
            price_spans = price_div.find_all('span')
            for span in price_spans:
                tmpPrice, tmpKm, tmpYear = process_price_span(span)
                if tmpPrice is not None:
                    price = tmpPrice
                if tmpKm is not None:
                    km = tmpKm
                if tmpYear is not None:
                    year = tmpYear
        
        # Samler all informasjon om bilen
        car_info = {
            "carId": car_id,
            "year": year,
            "price": price,
            "km": km,
            "make": make,
            "model": model,
            "freeTextModel": freeTextModel,
            "VIN": vin,
            "gear": gear,
            "fuelTypeId": fuelTypeId
        }
        
        # Legger til bilinformasjon i carData-listen
        carData.append(car_info)

def get_extended_car_data(car_id):
    vin = 0
    gear = 0
    fuelTypeId = 0
    attempt = 0
    
    carId = does_car_id_exist(car_id) 
    if (carId is None):
        url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
       
        while attempt < max_attempts:
            try:
                response = requests.get(url, timeout=10)  # Legger til en timeout på forespørselen
                response.raise_for_status()  # Legger til en sjekk for HTTP-statuskoder
                break  # Bryter ut av løkken hvis forespørselen lykkes
            except (ConnectTimeout, ConnectionError, requests.HTTPError) as e:
                attempt += 1
                if attempt < max_attempts:
                    print(f"Koblingstidsavbrudd oppstod. Venter 60 sekunder før forsøk {attempt + 1}.")
                    time.sleep(60)
                else:
                    print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")
                    return vin, gear, fuelTypeId

        soup = BeautifulSoup(response.text, 'html.parser')

            # Finn <section> elementet med den spesifikke klassen
        section = soup.find("section", class_="panel panel--bleed summary-icons")

        if section:
                # Innenfor dette <section> elementet, finn alle <div> elementer med klassen grid__unit u-pa8
            grid_units = section.find_all("div", class_="grid__unit u-pa8")
            for unit in grid_units:
                media_body = unit.find("div", class_="media__body")
                if media_body:
                    # Eksempel: Skriv ut første og andre <div> innhold innenfor media__body
                    divs = media_body.find_all("div")
                    if len(divs) >= 2:
                        if "Girkasse" in divs[0].text.strip():
                            gear = divs[1].text.strip()
                        elif "Drivstoff" in divs[0].text.strip():
                            fuelTypeId = FindFueltypeId(divs[1].text.strip())


        # Finn elementet som inneholder "Chassis nr. (VIN)"
        vin_title = soup.find("dt", text="Chassis nr. (VIN)")
        # Finn det neste `dd`-elementet som inneholder VIN-verdien
        if vin_title:
            vin_value = vin_title.find_next_sibling("dd")
            if vin_value:
                vin = vin_value.text.strip()

    return vin,gear,fuelTypeId

def process_price_span(span):
    text = span.text.strip().lower()
    price = None
    km = None
    year = None

    if text == 'solgt':
        price = 9
    elif "km" in text:
        km = text.replace("km", "").strip().replace('\xa0', '')  # Fjern "km" og strip hvite mellomrom
    elif "kr" in text:
        price = text.replace("kr", "").strip().replace('\xa0', '')
    else:
        try:
            year = int(text)  # Forsøk å konvertere til et tall (antageligvis et årstall)
        except ValueError:
            pass  # Dette var ikke et årstall
    
    return price, km, year

def main():
    # Base URL for the car page
    url = "https://www.finn.no/car/used/search.html"

    # Initialize the browser and get car models
    browser, car_brands = GetCarModels(url)
    model_inputs = browser.find_elements(By.CSS_SELECTOR, "ul.list.u-ml16 li div.input-toggle input[type='checkbox']")
    
    # Extract ID values from the found input elements
    model_ids = [input_elem.get_attribute('id') for input_elem in model_inputs]
    browser.quit()

    # Iterate over model IDs
    for model_id in model_ids:
        done = False
        attempt = 0

        while not done:
            for page_no in range(100):
                page_url = f'https://www.finn.no/car/used/search.html?{model_id.replace("-", "=")}&sales_form=1&sort=PUBLISHED_DESC&page={page_no + 1}'

                while attempt < max_attempts:
                    try:
                        response = requests.get(page_url, timeout=10)  # Add a timeout to the request
                        response.raise_for_status()  # Raise an error for bad status codes
                        break  # If request is successful, break out of the retry loop
                    except (ConnectTimeout, ConnectionError, requests.HTTPError) as e:
                        attempt += 1
                        if attempt < max_attempts:
                            print(f"Connection timeout occurred. Waiting 60 seconds before attempt {attempt + 1}.")
                            time.sleep(60)
                        else:
                            print(f"Connection timeout occurred after {max_attempts} attempts. Exiting.")
                            done = True
                            break

                if done:
                    break

                soup = BeautifulSoup(response.text, 'html.parser')
                car_tags = soup.find_all('article', {'class': ['sf-search-ad', 'sf-search-ad-legendary']})
                label = soup.find('label', attrs={'for': model_id})

                if label:
                    # Get only the direct text of the label, excluding text from <span> or other children
                    model = label.contents[0].strip() if label.contents else ''
                
                carData = []
                ExtractCarData(carData, car_tags, model)

                insert_car_and_price(carData)
                pagination = soup.find("a", {"class": "button button--pill button--has-icon button--icon-right"})

                if not pagination:
                    done = True
                    break

    return carData

def GetCarModels(url):

    browser = getBrowser(url)

    # Finn bilmerker og klikk på dem for å laste inn modellene
    car_brands = getCarBrands(browser)
    header_height = 49
    time.sleep(1)
    
    for brand in car_brands:
        # Scroller først elementet inn i visningen
        browser.execute_script("arguments[0].scrollIntoView(true);", brand)
        # Justerer deretter scroll-posisjonen for å ta høyde for headeren
        browser.execute_script(f"window.scrollBy(0, -{header_height});")
        brand.click()
        #time.sleep(2)  # Vent litt for å sikre at innholdet er lastet

    return browser,car_brands

def getCarBrands(browser):
    #car_brands = browser.find_elements(By.CSS_SELECTOR, "input[id^='make-'] + label")
    car_brands = browser.find_elements(By.CSS_SELECTOR, "a[href*='/mobility/search/car?make='] span")

    return car_brands

def accept_cookies(browser):
    try:
        # Finn iframe-elementet som inneholder samtykkeboksen
        iframe = WebDriverWait(browser, 5).until(
            EC.presence_of_element_located((By.XPATH, '//iframe[@title="SP Consent Message"]')))

        # Bytt til iframen
        browser.switch_to.frame(iframe)
        
        wait = WebDriverWait(browser, 5)
        godta_alle_knapp = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Godta alle')]")))
        godta_alle_knapp.click()
        # Bytt tilbake til hovedinnholdet, litt usikker på om denne trengs siden cookie boksen er borte
        browser.switch_to.default_content()

    except NoSuchElementException:
        pass

def getBrowser(url):
    options = webdriver.EdgeOptions()
    options.use_chromium = True  # Only for Edge version 79+
    #options.add_experimental_option("debuggerAddress", "localhost:9222")
    
    #options.add_argument("--headless")
    options.add_argument("--no-sandbox")  # Deaktiver sandbox for å unngå problemer i Docker
    options.add_argument("--disable-dev-shm-usage")  # Unngå begrensninger i /dev/shm
    options.add_argument("--verbose")

    browser = webdriver.Edge(options=options)
    #fixer ElementClickInterceptedException problemet som oppstår ved full liste
    browser.set_window_size(1920, 1280)
    #browser.maximize_window()

    browser.get(url)
    
    accept_cookies(browser)

    try:
        # Vent på at "Vis alle"-knappen skal bli tilgjengelig i DOM
        vis_alle_knapp = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(text(),'Vis alle')]")))

    except TimeoutException:
        browser.save_screenshot("timeout_exception.png")
        raise

    # Scroll til "Vis alle"-knappen før klikk
    browser.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -200);", vis_alle_knapp)
    time.sleep(1)  # La siden oppdatere
    # Fjern reklame-bakgrunnen
    #browser.execute_script("document.body.style.backgroundImage = 'none';")
    #browser.execute_script("document.body.style.backgroundColor = 'transparent';")    
    vis_alle_knapp.click()

    return browser

def getTimeStamp():
    now = datetime.now()
    formatted_date = now.strftime("Done! %d-%m-%Y %H:%M:%S")
    return formatted_date

if __name__ == "__main__":
    carData = main()
    print(getTimeStamp())
