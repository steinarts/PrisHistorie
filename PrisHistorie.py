import sqlite3
from contextlib import contextmanager
from contextlib import asynccontextmanager
import time
from bs4 import BeautifulSoup
from datetime import datetime
from requests.exceptions import ConnectTimeout
import aiohttp
import asyncio
import aiosqlite
import platform
from dataclasses import dataclass


headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
}
max_attempts = 3

@dataclass
class Car:
    id: int
    regNo: str
    make: str
    model: str
    heading: str
    location: str
    price: float
    url: str
    year: int
    km: int
    coordinates: str
    image: str
    timestamp: str
    status: str
    vin: str = None
    gearbox: str = None
    fuel: str = None

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
    # Returnerer ID for drivstofftypen, hardkodet for å slippe å hente fra db hver gang
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
        """, (car.id, car.make, car.model, car.year, car.km, car.gearbox, FindFueltypeId(car.fuel), car.vin, timestamp, car.heading))
    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"En bil med ID {car.id} eksisterer allerede i databasen.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def insert_price(cursor, car_id, price, timestamp):
    await cursor.execute("""
        INSERT INTO prices (car_id, price, timestamp)
        VALUES (?, ?, ?)
    """, (car_id, price, timestamp))

async def handle_existing_car(cursor, car, timestamp):
    
    if car.status == "Sold":
        inactiv_car_exists = await verify_inactive_car(cursor, car)
        if inactiv_car_exists is None:
            await move_car_to_inactive(cursor, car)
    else:
        await handle_price_update(cursor, car, timestamp)

async def handle_price_update(cursor, car, timestamp):
    #oppdaterer prisen hvis den er endret
    price_found = await get_current_price(cursor, car)
    # Sjekk om prisen er ny eller endret
    if not price_found or int(car.price) != int(price_found[0]):
        await insert_price(cursor, car.id, car.price, timestamp)

async def verify_inactive_car(cursor, car):
    await cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car.id,))
    car_exists = await cursor.fetchone()
    return car_exists

async def get_current_price(cursor, car):
    await cursor.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car.id,))
    price_found = await cursor.fetchone()
    return price_found

async def move_car_to_inactive(cursor, car):
    await cursor.execute("INSERT INTO inactivecars SELECT * FROM cars WHERE car_id = ?", (car.id,))
    await cursor.execute("DELETE FROM cars WHERE car_id = ?", (car.id,))

async def get_timestamp_db(cursor):
    return cursor.execute("SELECT datetime('now', 'localtime')").fetchone()[0]

def get_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

async def insert_car_and_price(session, queue):
    #legg til eller oppdater biloppføringer og priser i databasen
    while True:
        car = await queue.get()
        if car is None:  # Bryt når 'None' signaliserer slutten
            break
    
        async with db_connection() as conn:
            async with conn.cursor() as cursor:
                await process_car_entry(session, car, cursor)
                await conn.commit()
        # Simuler innsats med await asyncio.sleep(0.1)            
        queue.task_done()

async def process_car_entry(session, car, cursor):
    #Prosesserer bilinformasjon og oppdaterer databasen.
    now = get_timestamp()

    existing_car_id = await does_car_id_exist(cursor, car.id)
    if existing_car_id is None and car.status != 'Sold':
        await insert_new_car(session, car, cursor, now)
    else:
        await handle_existing_car(cursor, car, now)
        if car.price is None:
            print(f"{car.id} price is None")

async def insert_new_car(session, car, cursor, now):
     #Setter inn nye biloppføringer og deres pris i databasen.
    
    car_details = await get_extended_car_data(cursor, session, car.id)
    if car_details is None:
        print(f"Kunne ikke hente ytterligere detaljer for bil {car.id}.")
        return None
    
    """Oppdaterer Car-objectet med ekstra detaljer."""
    car.vin = car_details.get("VIN") if car_details else None
    car.model = car_details.get("Modell") if car_details else car.model
    car.gearbox = car_details.get("Girkasse") if car_details else None
    car.fuel = car_details.get("Drivstoff") if car_details else None
    
    await insert_car(cursor, car, now)
    await insert_price(cursor, car.id, car.price, now)

async def fetch_with_retry(url, session, parse_json=True, max_attempts=5):
    #Henter data fra en URL, returnerer JSON eller tekst.
    attempt = 0
    while attempt < max_attempts:
        try:
            async with session.get(url, headers=headers, timeout=10) as response:
                response.raise_for_status()
                return await response.json() if parse_json else await response.text()
                
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            attempt += 1
            print(f"Feil ved forespørsel til {url}: {e}")
            if attempt < max_attempts:
                print(f"Venter 10 sekunder før forsøk {attempt + 1}.")
                await asyncio.sleep(10)
            else:
                print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")
                return None

async def get_extended_car_data(cursor, session, car_id):
    carId = await does_car_id_exist(cursor, car_id) 
    if carId is None:
        url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
       
        response_text = await fetch_with_retry(url, session, parse_json=False, max_attempts=3)
        if response_text is None:
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
    """Henter navn og id fra bilmerker (make) og tilhørende modeller fra API-et."""
    makes_and_models = []
    data = await fetch_with_retry(api_url, session, parse_json=True)

    # Går gjennom 'filters' for å hente "make" og deres "models"
    return get_makes_with_models(data, makes_and_models)

def get_makes_with_models(data, makes_and_models):
    for filter_item in data.get('filters', []):
        if filter_item.get('name') == "make":  # Finn riktig seksjon for 'make'
            for make in filter_item.get('filter_items', []):
                make_name = make.get("display_name")  # Hovednavnet på bilmerket
                make_value = make.get("value")        # undernavnet til bilmerket
                models = get_models_from_make(make)

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

def get_models_from_make(make):
    models = []

    # Henter underliggende modeller hvis de finnes
    for model in make.get('filter_items', []):
        model_name = model.get("display_name")
        model_value = model.get("value")
        models.append({"model_name": model_name, "model_value": model_value})
    return models

async def fetch_ads_data(session, url, semaphore):
    async with semaphore:
        response_data = await fetch_with_retry(url, session, parse_json=True, max_attempts=3)
        return response_data.get("docs", [])
    
async def get_car_listings(queue, session, base_url, makes):
    
    semaphore = asyncio.Semaphore(20)  # Begrens til maksimum 20 samtidige forespørsler
    for make in makes:
        print(f"Bilmerke: {make['make_name']} (Value: {make['make_value']})")
        
        for model in make['models']:
            page = 1
            while True:
                url = f"{base_url}?model={model['model_value']}&page={page}"
                ads = await fetch_ads_data(session, url, semaphore)
                if not ads:
                    break
                
                for ad in ads:
                    listing = await build_listing(make, model, ad)
                    await queue.put(listing)  # Legg listing i køen

                page += 1
    # Signaliser at det ikke er flere biler å hente                
    await queue.put(None) 

async def build_listing(make, model, ad):
    return Car(
        id=ad.get("id"),
        regNo=ad.get("regno"),
        make=make["make_name"],
        model=model['model_name'],
        heading=ad.get("heading"),
        location=ad.get("location"),
        price=ad.get("price", {}).get("amount"),
        url=ad.get("canonical_url"),
        year=ad.get("year"),
        km=ad.get("mileage"),
        coordinates=ad.get("coordinates"),
        image=ad.get("image"),
        timestamp=ad.get("timestamp"),
        status="Sold" if "sold" in ad.get("flags", []) else "Available"
    )

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
    print(getTimeStamp("Oppdatering av priser og biler startet:"))
    # fixing event loop is closed error in windows
    print(f"Platform: {platform.system()}")
    if platform.system()=='Windows':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
    print(getTimeStamp("Oppdatering av priser og biler fullført:"))
