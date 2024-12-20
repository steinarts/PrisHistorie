import sqlite3
from contextlib import contextmanager

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
from requests.exceptions import ConnectTimeout

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
        c.execute("SELECT id FROM fueltypes WHERE LOWER(type) = LOWER(?)", (drivstoff,))
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
        """, (car['id'], car['make'], car['model'], car['year'], car['km'], car['gearbox'], FindFueltypeId(car['fuel']), car['vin'], timestamp, car['heading']))
    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"En bil med ID {car['id']} eksisterer allerede i databasen.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

def insert_price(cursor, car_id, price, timestamp):
    cursor.execute("""
        INSERT INTO prices (car_id, price, timestamp)
        VALUES (?, ?, ?)
    """, (car_id, price, timestamp))

def handle_existing_car(cursor, car, timestamp):
    
    if car['status'] == "Sold":
        print(f"Car {car['id']} is sold")
        cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car['id'],))
        car_exists = cursor.fetchone()
        if car_exists is None:
            cursor.execute("INSERT INTO inactivecars SELECT * FROM cars WHERE car_id = ?", (car['id'],))
            cursor.execute("DELETE FROM cars WHERE car_id = ?", (car['id'],))
    else:
        cursor.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car['id'],))
        price_found = cursor.fetchone()
        if price_found:
            if int(car['price']) != int(price_found[0]):
                insert_price(cursor, car['id'], car['price'], timestamp)
        else:
            insert_price(cursor, car['id'], car['price'], timestamp)

def insert_car_and_price(carData):
    with db_connection() as conn:
        c = conn.cursor()
        now = c.execute("SELECT datetime('now', 'localtime')").fetchone()[0]

        for car in carData:
            existing_car_id = does_car_id_exist(car['id'])
            if existing_car_id is None and car['status'] != 'Sold':
                car_details = get_extended_car_data(car['id'])
                car.update({
                        "vin": car_details.get("VIN") if car_details else None,  # Legger til VIN
                        "model": car_details.get("Modell") if car_details else None,  # Modell
                        "gearbox": car_details.get("Girkasse") if car_details else None,  # Girkasse
                        "fuel": car_details.get("Drivstoff") if car_details else None,  # Drivstoff
                    })
                insert_car(c, car, now)
                insert_price(c, car['id'], car['price'], now)
            else:
                handle_existing_car(c, car, now)
                if car['price'] is None:
                    print(f"{car['id']} price is None")

            conn.commit()

def get_extended_car_data(car_id):
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
                    return None

        soup = BeautifulSoup(response.text, 'html.parser')

        # Funksjon for å hente verdien basert på overskrift (dt)
        def get_spec_value(label):
            for dt in soup.find_all('dt', class_='s-text-subtle'):
                if label in dt.get_text(strip=True):  # Strip fjerner HTML-kommentarer
                    value_tag = dt.find_next_sibling('dd')
                    return value_tag.get_text(strip=True) if value_tag else None
            return None
    
        # Henter spesifikasjonene
        vin = get_spec_value('Chassis nr. (VIN)')
        model = get_spec_value('Modell')
        gearbox = get_spec_value('Girkasse')
        fuel = get_spec_value('Drivstoff')

        return {
            'VIN': vin,
            'Modell': model,
            'Girkasse': gearbox,
            'Drivstoff': fuel
        }

def get_car_makes(api_url):

    """Henter bilmerker (make) og tilhørende modeller fra API-et."""
    response = requests.get(api_url)
    if response.status_code != 200:
        raise Exception("Kunne ikke hente make-data.")
    
    data = response.json()  # Konverterer responsen til JSON
    makes_and_models = []

    # Går gjennom 'filters' for å hente "make" og deres "models"
    for filter_item in data.get('filters', []):
        if filter_item.get('name') == "make":  # Finn riktig seksjon for 'make'
            for make in filter_item.get('filter_items', []):
                make_name = make.get("display_name")  # Hovednavnet på bilmerket
                make_value = make.get("value")        # Verdien til bilmerket
                models = []

                # Henter underliggende modeller hvis de finnes
                for model in make.get('filter_items', []):
                    model_name = model.get("display_name")
                    model_value = model.get("value")
                    models.append({"model_name": model_name, "model_value": model_value})

                # Legger til make og modeller i resultatlisten
                makes_and_models.append({
                    "make_name": make_name,
                    "make_value": make_value,
                    "models": models
                })
    
    return makes_and_models

def get_car_listings(base_url, makes):
    """
    Itererer gjennom bilmerker og sider, og henter alle bilannonser.
    
    Args:
        base_url (str): Basis-URL til API-et.
        makes (list): Liste med bilmerker i format {'name': display_name, 'value': make-ID}.
    
    Returns:
        list[dict]: Liste med alle annonser i format {'make': ..., 'heading': ..., 'price': ..., 'url': ...}.
    """
    all_listings = []

    for make in makes:
        print(f"Bilmerke: {make['make_name']} (Value: {make['make_value']})")
        
        for model in make['models']:
            #print(f"  - Modell: {model['model_name']} (Value: {model['model_value']})")
            page = 1
            
            while True:
                # Bygg URL med make-ID og page
                url = f"{base_url}?model={model['model_value']}&page={page}"
                
                try:
                    response = requests.get(url)
                    
                    # Bryt løkken hvis responsen gir 400 (Bad Request)
                    if response.status_code == 400:
                        print(f"(400) Ingen flere sider for {make['make_name']} (page {page})")
                        break
                    
                    response.raise_for_status()
                    data = response.json()

                    # Hent annonser fra JSON
                    ads = data.get("docs", [])
                    if not ads:
                        #print(f"Ingen annonser funnet for {make['make_name'], model['model_name']} (page {page})")
                        # tomt for annonser på dette merket, lagrer dataen
                        insert_car_and_price(all_listings)
                        all_listings.clear()
                        break
                    
                    # Lagre relevant data fra hver annonse
                    for ad in ads:
                        listing = {
                            "id": ad.get("id"),
                            "regNo": ad.get("regno"),
                            "make": make["make_name"],
                            "model": model['model_name'],
                            "heading": ad.get("heading"),
                            "location": ad.get("location"),
                            "price": ad.get("price", {}).get("amount"),
                            "url": ad.get("canonical_url"),
                            "year": ad.get("year"),
                            "km": ad.get("mileage"),
                            "status": "Sold" if "sold" in ad.get("flags", []) else "Available"  # Sjekker flag for "sold"
                        }
                        all_listings.append(listing)

                    # Øk sidetallet for neste forespørsel
                    page += 1
                    time.sleep(0.5)  # Begrens antall forespørsler per sekund for å unngå blokkering
                

                except requests.exceptions.RequestException as e:
                    print(f"Feil ved henting av annonser: {e}")
                    break

    return all_listings


def main():
    # Base URL for the car page
    # URL til API-en
    api_url = "https://www.finn.no/mobility/search/api/search/SEARCH_ID_CAR_USED"

    # Kall funksjonen
    car_makes = get_car_makes(api_url)
    listings = get_car_listings(api_url,car_makes)

def getTimeStamp():
    now = datetime.now()
    formatted_date = now.strftime("Done! %d-%m-%Y %H:%M:%S")
    return formatted_date

if __name__ == "__main__":
    carData = main()
    print(getTimeStamp())
