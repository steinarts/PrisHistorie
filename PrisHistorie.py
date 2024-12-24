import sqlite3
from contextlib import contextmanager
from contextlib import asynccontextmanager
import time
#import requests
from bs4 import BeautifulSoup
#import time
from datetime import datetime
from requests.exceptions import ConnectTimeout
import aiohttp
import asyncio
import aiosqlite
import platform

#from aiohttp import ClientSession

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
}
max_attempts = 5

@contextmanager
def db_connection():
    conn = sqlite3.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        conn.close()

@asynccontextmanager
async def db_connection():
    conn = await aiosqlite.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        await conn.close()

def async_tidtaker(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        print(f"'{func.__name__}' tok {end_time - start_time:.6f} sekunder")
        return result
    return wrapper

def FindFueltypeId(drivstoff):
    if drivstoff is None:
        return None
      
    fuelTypeMap = {
        'diesel': 1,
        'bensin': 2,
        'hybrid': 3,
        'elektrisitet': 4,
        'gass + bensin': 5,
        'hydrogen': 6,
        'el + diesel': 7,
        'el + bensin': 8
    }
    return fuelTypeMap.get(drivstoff.lower())

async def does_car_id_exist(cursor, car_id):
    carId = None
    
    await cursor.execute("SELECT car_id FROM cars WHERE car_id = ? LIMIT 1", (car_id,))
    car = await cursor.fetchone()

    if car is not None:
        carId = car[0]
    return carId

async def insert_car(cursor, car, timestamp):
    try:
        await cursor.execute("""
            INSERT INTO cars (car_id, make, model, year, km, gear, fuelTypeId, vin, timestamp, freeTextModel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (car['id'], car['make'], car['model'], car['year'], car['km'], car['gearbox'], FindFueltypeId(car['fuel']), car['vin'], timestamp, car['heading']))
    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"En bil med ID {car['id']} eksisterer allerede i databasen.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def insert_price(cursor, car_id, price, timestamp):
    await cursor.execute("""
        INSERT INTO prices (car_id, price, timestamp)
        VALUES (?, ?, ?)
    """, (car_id, price, timestamp))

async def handle_existing_car(cursor, car, timestamp):
    
    if car['status'] == "Sold":
        #print(f"Car {car['id']} is sold")
        await cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car['id'],))
        car_exists = await cursor.fetchone()
        if car_exists is None:
            await cursor.execute("INSERT INTO inactivecars SELECT * FROM cars WHERE car_id = ?", (car['id'],))
            await cursor.execute("DELETE FROM cars WHERE car_id = ?", (car['id'],))

    else:
        await cursor.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car['id'],))
        price_found = await cursor.fetchone()
        if price_found:
            if int(car['price']) != int(price_found[0]):
                await insert_price(cursor, car['id'], car['price'], timestamp)
        else:
            await insert_price(cursor, car['id'], car['price'], timestamp)

async def get_timestamp_db(cursor):
    return cursor.execute("SELECT datetime('now', 'localtime')").fetchone()[0]

def get_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

async def insert_car_and_price(session, queue):
    
    while True:
        car = await queue.get()
        if car is None:  # Bryt når 'None' signaliserer slutten
            break
    
        async with db_connection() as conn:
            async with conn.cursor() as cursor:
                #now = c.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
                now = get_timestamp()

                #for car in carData:
                existing_car_id = await does_car_id_exist(cursor, car['id'])
                if existing_car_id is None and car['status'] != 'Sold':
                    car_details = await get_extended_car_data(cursor, session, car['id'])
                    car.update({
                            "vin": car_details.get("VIN") if car_details else None,  # Legger til VIN
                            "model": car_details.get("Modell") if car_details else None,  # Modell
                            "gearbox": car_details.get("Girkasse") if car_details else None,  # Girkasse
                            "fuel": car_details.get("Drivstoff") if car_details else None,  # Drivstoff
                        })
                    await insert_car(cursor, car, now)
                    await insert_price(cursor, car['id'], car['price'], now)
                else:
                    await handle_existing_car(cursor, car, now)
                    if car['price'] is None:
                        print(f"{car['id']} price is None")

                await conn.commit()
        # Simuler innsats med await asyncio.sleep(0.1)            
        queue.task_done()

async def fetch(url, session):
    try:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientError as e:
        print(f"Feil ved forespørsel til {url}: {e}")

async def get_extended_car_data(cursor, session, car_id):
    attempt = 0
    carId = await does_car_id_exist(cursor, car_id) 
    if carId is None:
        url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
       
        #async with aiohttp.ClientSession() as session:
        while attempt < max_attempts:
            try:
                async with session.get(url, timeout=10) as response:
                    response.raise_for_status()
                    response_text = await response.text()
                    break
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt < max_attempts:
                    print(f"Koblingstidsavbrudd oppstod. Venter 60 sekunder før forsøk {attempt + 1}.")
                    await asyncio.sleep(60)
                else:
                    print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")
                    return None

        soup = BeautifulSoup(response_text, 'lxml')

        # Funksjon for å hente verdien basert på overskrift (dt)
        def get_spec_value(label):
            for dt in soup.find_all('dt', class_='s-text-subtle'):
                if label in dt.get_text(strip=True):
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

async def get_car_makes(session, api_url):
    """Henter bilmerker (make) og tilhørende modeller fra API-et."""
    async with session.get(api_url) as response:
        response.raise_for_status()
        data = await response.json()
    
    makes_and_models = []
    restrictor = 0

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
                #restrictor += 1
                #if restrictor == 10:
                #    break # breaker her for tesing only
        
    return makes_and_models

async def get_car_listings(queue, session, base_url, makes):
    
    semaphore = asyncio.Semaphore(20)  # Begrens til maksimum 20 samtidige forespørsler
    for make in makes:
        print(f"Bilmerke: {make['make_name']} (Value: {make['make_value']})")
        
        for model in make['models']:
            page = 1
            while True:
                url = f"{base_url}?model={model['model_value']}&page={page}"
                try:
                    async with semaphore:  # Sjekker for å begrense samtidighet
                        data = await fetch(url, session)
                        #response.raise_for_status()
                        #data = await response.json()

                        # Hent annonser fra JSON
                        ads = data.get("docs", [])
                        if not ads:
                            break
                        
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
                                "status": "Sold" if "sold" in ad.get("flags", []) else "Available"
                            }
                            #all_listings.append(listing)
                            await queue.put(listing)  # Legg listing i køen

                    page += 1
                    #await asyncio.sleep(0.5)
                
                except aiohttp.ClientError as e:
                    print(f"Feil ved henting av annonser: {e}")
                    break
                except asyncio.TimeoutError:
                    print(f"Timeout ved å hente URL: {url}")
                    break

    #return all_listings
    await queue.put(None)  # Signaliser at det ikke kommer flere annonser

async def main():
    api_url = "https://www.finn.no/mobility/search/api/search/SEARCH_ID_CAR_USED"
    async with aiohttp.ClientSession() as session:
        car_makes = await get_car_makes(session, api_url)
        queue = asyncio.Queue()

        # Kjør både henting og innsats parallelt
        producer = asyncio.create_task(get_car_listings(queue, session, api_url, car_makes))
        consumer = asyncio.create_task(insert_car_and_price(session, queue))

        await producer  # Venter på at produsenten skal avslutte
        # Signaliser til konsumerende task (en gang er nok)
        await queue.put(None)

        await consumer  # Vent på at konsumeren er ferdig

def getTimeStamp(msg):
    now = datetime.now()
    formatted_date = f"{msg} {now.strftime('%d-%m-%Y %H:%M:%S')}"
    return formatted_date

if __name__ == "__main__":
    #carData = main()
    print(getTimeStamp("Oppdatering av priser og biler startet:"))
    # fixing event loop is closed error in windows
    print(f"Platform: {platform.system()}")
    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
    print(getTimeStamp("Oppdatering av priser og biler fullført:"))
