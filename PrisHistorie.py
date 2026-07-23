import sqlite3
from contextlib import contextmanager
from contextlib import asynccontextmanager
import time
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from requests.exceptions import ConnectTimeout
import aiohttp
import asyncio
import aiosqlite
import platform
import os
from dataclasses import dataclass
from dbFunctions import  update_status_check_progress,UpdateModelNoOnCars, FindCarsForUpdateOfStatus, UpdateFreeTextOnCars, FindCarsForUpdateOfFreetext, UpdateVinOnCars, UpdateRegNoOnInactiveCars, FindCarsForUpdateOfVin, FindCarsForUpdateOfRegNo, UpdateVinOnInactiveCar, move_car_to_inactive, verify_inactive_car, get_current_price, insert_price, does_car_id_exist, insert_car, findOrCreateBodyTypeId
from KjoretoyAPI import hent_kjoretoydata
from vin_validation import is_valid_vin
from api_health_check import ApiHealthCheck
import locale
from dateUtils import (
    convert_date_format_fra_annonse,
    convert_iso_to_standard_format,
)

# Last miljøvariabler fra .env fil hvis den finnes
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv ikke installert, bruk systemets miljøvariabler

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
}
max_attempts = 3
db_write_lock = asyncio.Lock()

class VegvesenRateLimitError(Exception):
    """
    Custom exception raised when Vegvesen API returns HTTP 429 (rate limit exceeded).
    Allows different handling strategies for rate limits vs other API errors.
    
    @param message: Error message describing the rate limit condition (str)
    @param retryAfter: Seconds to wait before retrying, if provided by API (int)
    """
    def __init__(self, message="Vegvesen API rate limit exceeded", retryAfter=None):
        self.retryAfter = retryAfter
        super().__init__(message)

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
    latitude : float
    longitude : float
    image: str
    timestamp: str
    status: str
    dealerSegmentId: int    
    vin: str = None
    gearbox: str = None
    fuel: str = None
    organisationName: str = None

def is_valid_regno(regno):
    """
    Validates if a Norwegian registration number is potentially valid.
    Norwegian RegNo format: 2 letters + 5 digits (e.g., AB12345).
    
    @param regno: Registration number string to validate
    @return: True if RegNo appears valid, False otherwise
    @throws: None
    @author: GitHub Copilot
    """
    if not regno or regno in ["None", "NO NUMBER", "UREGISTRERT", ""]:
        return False
    if not isinstance(regno, str):
        return False
    # Remove spaces and check length
    clean_regno = regno.replace(" ", "").upper()
    if len(clean_regno) != 7:
        return False
    # Check format: 2 letters + 5 digits
    if not (clean_regno[:2].isalpha() and clean_regno[2:].isdigit()):
        return False
    return True


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
    await conn.execute("PRAGMA journal_mode=WAL;")
    await conn.execute("PRAGMA busy_timeout = 5000;")  # 5 sekunder
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.commit()
    try:
        yield conn
    finally:
        await conn.close()

@asynccontextmanager
async def db_connection_locked():
    async with db_write_lock:             # ← 1 writer om gangen
        async with db_connection() as conn:
            yield conn
            
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
        'el + bensin': 8,
        'el': 9,
        'hybrid bensin': 10,
        'plug-in diesel': 11,
        'hybrid diesel': 12,
        'plug-in bensin': 13
    }
    return fuelTypeMap.get(drivstoff.lower())

def FindDealerSegmentId(dealer_segment):
    # Returnerer ID for dealer_segment, hardkodet for å slippe å hente fra db hver gang
    if dealer_segment is None:
        return None
      
    dealer_segmentMap = {
        'privat': 1,
        'forhandler': 2,
        'merkeforhandler': 3
    }
    return dealer_segmentMap.get(dealer_segment.lower())

async def handle_existing_car(cursor, car, timestamp):
    
    if car.status == "Sold":
        inactiv_car_exists = await verify_inactive_car(cursor, car)
        if inactiv_car_exists is None:
            now = get_timestamp()
            await move_car_to_inactive(car.id, now)
    else:
        await handle_price_update(cursor, car, timestamp)

async def handle_price_update(cursor, car, timestamp):
    #oppdaterer prisen hvis den er endret
    price_found = await get_current_price(cursor, car)
    # Sjekk om prisen er ny eller endret
    if not price_found or int(car.price) != int(price_found[0]):
        await insert_price(cursor, car.id, car.price, timestamp)

def get_timestamp():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


async def insert_car_and_price(session, queue):
    """
    Legg til eller oppdater biloppføringer og priser i databasen.
    Prosesserer biler fra køen og skriver til database med progress tracking.
    
    @param session: aiohttp ClientSession for HTTP requests
    @param queue: asyncio.Queue med Car objects fra producer
    @return: None
    @throws: aiosqlite.Error ved database-feil
    @author: GitHub Copilot
    """
    import time
    
    startTime = time.time()
    runStartTimestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    processedCount = 0
    newCarsInserted = 0
    existingCarsUpdated = 0
    
    print(f"\n{'='*60}")
    print(f"📊 CONSUMER STARTED - Processing queue")
    print(f"{'='*60}\n")
    
    while True:
        car = await queue.get()
        if car is None:
            break
    
        async with db_connection() as conn:
            async with conn.cursor() as cursor:
                existingCarId = await does_car_id_exist(cursor, car.id)
                
                if existingCarId is None and car.status != 'Sold':
                    newCarsInserted += 1
                elif existingCarId is not None:
                    existingCarsUpdated += 1
                
                await process_car_entry(session, car, cursor)
                await conn.commit()
        
        processedCount += 1
        
        if processedCount % 100 == 0:
            elapsed = time.time() - startTime
            rate = processedCount / elapsed if elapsed > 0 else 0
            print(f"📊 Progress: {processedCount} cars processed ({rate:.1f} cars/sec, {newCarsInserted} new, {existingCarsUpdated} updated)")
        
        queue.task_done()
    
    totalElapsed = time.time() - startTime
    runStopTimestamp = datetime.now().strftime('%d-%m-%Y %H:%M:%S')
    overallRate = processedCount / totalElapsed if totalElapsed > 0 else 0
    
    print(f"\n{'='*60}")
    print(f"✅ CONSUMER COMPLETED")
    print(f"   Total processed: {processedCount}")
    print(f"   New cars inserted: {newCarsInserted}")
    print(f"   Existing cars updated: {existingCarsUpdated}")
    print(f"   Start time: {runStartTimestamp}")
    print(f"   Stop time: {runStopTimestamp}")
    print(f"   Time: {totalElapsed:.1f}s")
    print(f"   Rate: {overallRate:.1f} cars/sec")
    print(f"{'='*60}\n")


async def process_car_entry(session, car, cursor):
    #Prosesserer bilinformasjon og oppdaterer databasen.
    now = get_timestamp()

    existing_car_id = await does_car_id_exist(cursor, car.id)
    if existing_car_id is None and car.status != 'Sold':
        await insert_new_car(session, car, cursor, now)
    #elif existing_car_id is None and car.status == 'Sold':
        # Hvis bilen er solgt og allered registert i databasen, ignorerer vi den.
    elif existing_car_id is not None:
        await handle_existing_car(cursor, car, now)
        if car.price is None:
            print(f"{car.id} price is None")

async def insert_new_car(session, car, cursor, now):
     #Setter inn nye biloppføringer og deres pris i databasen.
    carId = await does_car_id_exist(cursor, car.id  ) 
    if carId is None:

        car_details = await get_extended_car_data(cursor, session, car.id)
        await get_statusdata_on_car(cursor, session, car.id)
    if car_details is None:
        print(f"Kunne ikke hente ytterligere detaljer for bil {car.id}.")
        return None
    
    """Oppdaterer Car-objectet med ekstra detaljer."""
    if car_details.get("VIN") is None and car_details.get("RegNr") is not None:
        await GetUnderstellsnummerFromRegNr(car_details)

    bodyTypeId = await findOrCreateBodyTypeId(cursor, car_details.get("Karosseri"))
    car.vin = car_details.get("VIN") if car_details else None
    car.model = car_details.get("Modell") if car_details else car.model
    car.gearbox = car_details.get("Girkasse") if car_details else None
    car.fuel = car_details.get("Drivstoff") if car_details else None
    car.bodyTypeId = bodyTypeId  # ✅ Add the BodyTypeId to the Car object

    await insert_car(cursor, car, now)
    await insert_price(cursor, car.id, car.price, now)

async def GetUnderstellsnummerFromRegNr(car_details):
    """
    Fetches VIN from Vegvesen API using registration number.
    Handles rate limiting gracefully by setting VIN to None.
    
    @param car_details: Dictionary containing RegNr and car_id
    @return: None - updates car_details in place
    @throws: None - VegvesenRateLimitError is caught and logged
    @author: GitHub Copilot
    """
    try:
        parameter = "kjennemerke"
        resultat = await hent_kjoretoydata(parameter, car_details.get("RegNr"))
        
        if resultat and "understellsnummer" in resultat:
            car_details["VIN"] = resultat["understellsnummer"]
            print("Hentet understellsnummer fra Kjøretøy-API-et", car_details["VIN"])
        else:
            car_details["VIN"] = None
            print("Kunne ikke hente understellsnummer", car_details["car_id"])
    
    except VegvesenRateLimitError as e:
        # ✅ Rate limit hit - log and continue without VIN
        print(f"⚠️ {e} - Continuing without VIN for car {car_details.get('car_id')}")
        car_details["VIN"] = None

async def GetRegNrFromUnderstellsnummer(car_details):
    """
    Fetches RegNo from Vegvesen API using VIN.
    Handles rate limiting gracefully by setting RegNo to None.
    
    @param car_details: Dictionary containing VIN and car_id
    @return: None - updates car_details in place
    @throws: None - VegvesenRateLimitError is caught and logged
    @author: GitHub Copilot
    """
    try:
        parameter = "understellsnummer"
        resultat = await hent_kjoretoydata(parameter, car_details.get("VIN"))
        
        if resultat and "kjennemerke" in resultat:
            car_details["RegNr"] = resultat["kjennemerke"]
            print("Hentet kjennemerke fra Kjøretøy-API-et", car_details["RegNr"])
        else:
            car_details["RegNr"] = None
            print("Kunne ikke hente kjennemerke", car_details["car_id"])
    
    except VegvesenRateLimitError as e:
        # ✅ Rate limit hit - log and continue without RegNo
        print(f"⚠️ {e} - Continuing without RegNo for car {car_details.get('car_id')}")
        car_details["RegNr"] = None

async def fetch_with_retry(url, session, parse_json=True, max_attempts=5):
    """
    Fetches data from a URL with retry logic. Stops retrying on rate-limiting (429) errors.
    """
    attempt = 0
    while attempt < max_attempts:
        try:
            async with session.get(url, headers=headers, timeout=5) as response:
                if response.status == 429:  # Too Many Requests
                    retry_after = int(response.headers.get("Retry-After", 0))  # Default to 0 seconds if not provided
                    print(f"⚠️ Rate limit hit. Stopping retries. Retry-After: {retry_after} seconds.")
                    return None  # Stop retrying and return None
                if response.status == 204:  # No Content
                    print(f"⚠️ HTTP 204 No Content for URL {url}. Data: {response.request_info}")
                    return None
                response.raise_for_status()
                return await response.json() if parse_json else await response.text()
        except aiohttp.ClientResponseError as e:
            #print(f"❌ HTTP error {e.status} for URL {url}: {e.message}")
            if e.status == 429:
                print("⚠️ Stopping retries due to rate limit (429).")
                return None  # Stop retrying and return None
            elif e.status == 404:
                #print(f"❌ 404 Not Found for URL {url}.")
                return "404"
            else:
                attempt += 1
                if attempt < max_attempts:
                    print(f"Retrying ({attempt}/{max_attempts})...")
                    await asyncio.sleep(5)
                else:
                    print(f"❌ Max retries reached for {url}. Giving up.")
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            attempt += 1
            print(f"❌ Error during request to {url}")
            print(f"   Error details: {e}")
            if attempt < max_attempts:
                print(f"Retrying ({attempt}/{max_attempts})...")
                await asyncio.sleep(5)
            else:
                print(f"❌ Max retries reached for {url}. Giving up.")
                return None

async def get_statusdata_on_car(cursor, session, car_id):
        #url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
        url = 'https://www.finn.no/mobility/item/' + str(car_id)
        response_text = await fetch_with_retry(url, session, parse_json=False, max_attempts=3)
        if response_text == "404":
            return "404_NOT_FOUND"
        
        if response_text is None:
            return None
        
        soup = BeautifulSoup(response_text, 'lxml')

        #badge-negative-background = inactive 
        div_element = soup.find('div', class_='py-4 px-8 border-0 rounded-4 text-xs inline-flex bg-[--w-color-badge-negative-background] s-text')
        # Hent teksten inne i div-elementet
        if div_element:
            status = div_element.get_text(strip=True)
            #print(f"Teksten er: {status}")
        else:
            #badge-waring-background = solgt
            div_element = soup.find('div', class_='py-4 px-8 border-0 rounded-4 text-xs inline-flex bg-[--w-color-badge-warning-background] s-text')
            if div_element:
                status = div_element.get_text(strip=True)
                #print(f"Teksten er: {status}")
            else:

                #print("Elementet ble ikke funnet.")
                return None
            
        overordnet_div = soup.find('div', class_='md:col-span-3')
        if overordnet_div:
            # Finn <p>-elementet som inneholder "Sist endret"
            sist_endret_p = overordnet_div.find('p', class_='s-text-subtle mb-0', string='Sist endret')
            
            if sist_endret_p:  # ✅ Check if the paragraph exists before calling find_parent
                sist_endret_div = sist_endret_p.find_parent('div')
                
                if sist_endret_div:
                    # Finn datoen i det tilhørende <p>-elementet
                    dato_element = sist_endret_div.find('p', class_='font-bold whitespace-nowrap mb-0 md:mt-8')
                    
                    if dato_element:
                        dato = dato_element.get_text(strip=True)
                        #print(f"Datoen for sist endret er: {dato}")
                    else:
                        print("Datoen for sist endret ble ikke funnet.")
                        dato = None  # ✅ Set default value when date is not found
                else:
                    print("Parent div for 'Sist endret' ble ikke funnet.")
                    dato = None  # ✅ Set default value when parent div is not found
            else:
                #print("Elementet med 'Sist endret' ble ikke funnet.")
                dato = None  # ✅ Set default value when "Sist endret" paragraph is not found
        else:
            #print("Overordnet <div>-element ble ikke funnet.")
            dato = None  # ✅ Set default value when main div is not found

        return status, dato

async def get_extended_car_data(cursor, session, car_id):
        #url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
        url = 'https://www.finn.no/mobility/item/' + str(car_id)
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
    
        def get_image_link():
            img_tag = soup.find('img', {'srcset': True})
            if img_tag is None:
                return ""
            # Extract the srcset attribute
            srcset = img_tag['srcset']
            # Hent den første URL-en i srcset
            first_url = srcset.split(',')[0].strip().split(' ')[0]
            # Del opp URL-en for å hente base_url
            base_url = first_url.split('/dynamic/')[0]  # Henter "https://images.finncdn.no"
            # Hent den dynamiske delen
            dynamic_part = first_url.split('/dynamic/')[1].split('/', 1)[1]
            # Konstruer den fullstendige "default"-URL-en
            default_image_url = f"{base_url}/dynamic/default/{dynamic_part}"
            return default_image_url        

        def get_freetext_value():
            # Finn <h1>-elementet og hent teksten
                titleObj = soup.find('h1', class_='t1')
                if titleObj is not None:
                    title = titleObj.text
                else: 
                    title = None
                
                # ✅ Add None check before accessing .text
                descriptionObj = soup.find('p', class_='s-text-subtle')
                if descriptionObj is None:
                    return title  # ✅ Fallback to title if no description
                
                description = descriptionObj.text  # ✅ Safe - we know it exists!
                
                if description == "FINN-kode":
                    return title
                return description

        # Henter spesifikasjonene
        vin = get_spec_value('Chassis nr. (VIN)')
        model = get_spec_value('Modell')
        gearbox = get_spec_value('Girkasse')
        fuel = FindFueltypeId(get_spec_value('Drivstoff'))
        regNo = get_spec_value('Registreringsnummer')
        modelYear = get_spec_value('Modellår')
        Kilometerstand = get_spec_value('Kilometerstand')
        karosseri = get_spec_value('Karosseri')
        imageLink = get_image_link()
        freeTextModel = get_freetext_value()

        return {
            'VIN': vin,
            'Modell': model,
            'Girkasse': gearbox,
            'Drivstoff': fuel,
            'RegNr': regNo,
            'Modellår': modelYear,
            'Kilometerstand': Kilometerstand,
            'Karosseri': karosseri,
            'car_id': car_id,
            'imageLink': imageLink,
            'freeTextModel': freeTextModel
        }

async def get_car_makes(session, api_url):
    """Henter navn og id fra bilmerker (make) og tilhørende modeller fra API-et."""
    makes_and_models = []
    data = await fetch_with_retry(api_url, session, parse_json=True)
    
    # 🔍 Health check: Verifiser API-struktur
    healthCheck = ApiHealthCheck()
    if not healthCheck.checkFinnApiStructure(data):
        print(healthCheck.getReport())
        healthCheck.logResults()
        healthCheck.sendEmailAlert("🚨 KRITISK: Finn.no API har endret struktur!")
        raise Exception("❌ KRITISK: Finn.no API har endret struktur! Sjekk logs/api_health_check.log")
    
    if healthCheck.hasWarnings():
        print(healthCheck.getReport())
        healthCheck.logResults()
        healthCheck.sendEmailAlert("⚠️ Finn.no API advarsler")

    # Går gjennom 'filters' for å hente "make" og deres "models"
    return get_makes_with_models(data, makes_and_models)

def get_makes_with_models(data, makes_and_models):
    for filter_item in data.get('filters', []):
        if filter_item.get('name') == "variant":  # ✅ Finn variant-filteret
            print(f"✅ Fant {len(filter_item.get('filter_items', []))} bilmerker i variant-filteret")
            
            for make in filter_item.get('filter_items', []):
                make_name = make.get("display_name")  # Bilmerke (Abarth, AC, etc.)
                make_value = make.get("value")
                models = get_models_from_make(make)  # Hent modellserier og modeller

                makes_and_models.append({
                    "make_name": make_name,
                    "make_value": make_value,
                    "models": models
                })
        
    return makes_and_models

def get_models_from_make(make):
    """
    Henter modellserier (nivå 1) og spesifikke modeller (nivå 2) fra et bilmerke.
    Struktur: Merke -> Modellserie -> Spesifikk modell
    Eksempel: Abarth -> 500-Serie -> [500, 595]
    """
    models = []

    # Nivå 1: Modellserier (f.eks. "500-Serie", "Cobra")
    for model_series in make.get('filter_items', []):
        series_name = model_series.get("display_name")
        series_value = model_series.get("value")
        
        # Sjekk om det finnes spesifikke modeller under denne serien (nivå 2)
        sub_models = model_series.get('filter_items', [])
        
        if sub_models:
            # Hvis det finnes sub-modeller, legg til hver enkelt
            for sub_model in sub_models:
                models.append({
                    "model_name": f"{series_name} - {sub_model.get('display_name')}",  # "500-Serie - 500"
                    "model_value": sub_model.get("value")
                })
        else:
            # Ingen sub-modeller, bruk modellserien direkte
            models.append({
                "model_name": series_name,
                "model_value": series_value
            })
    
    return models

async def fetch_ads_data(session, url, semaphore):
    async with semaphore:
        response_data = await fetch_with_retry(url, session, parse_json=True, max_attempts=3)
        if response_data is None:
            return []
        return response_data.get("docs", [])
    
# ✅ Din originale fungerende kode + logging!
async def get_car_listings(queue, session, base_url, makes):
    import time
    
    overallStartTime = time.time()  # ✅ Start timing
    totalAdsScraped = 0
    
    print("🚀 PRODUCER STARTED - Scraping API")
    
    semaphore = asyncio.Semaphore(20)
    for make in makes:
        makeStartTime = time.time()  # ✅ Timing per bilmerke
        makeAdsCount = 0
        
        print(f"🔍 Scraping {make['make_name']}...", end='', flush=True)
        
        for model in make['models']:
            page = 1
            consecutive_failures = 0
            max_consecutive_failures = 2
            
            while True:
                url = f"{base_url}?model={model['model_value']}&page={page}&sales_form=1"
                ads = await fetch_ads_data(session, url, semaphore)
                
                if ads is None:
                    # Feil ved henting av data
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        # Hopp over denne modellen hvis vi får for mange feil
                        break
                    await asyncio.sleep(2)
                    continue
                
                if not ads:
                    # Ingen flere annonser
                    break
                
                # Reset failure counter ved suksess
                consecutive_failures = 0
                
                for ad in ads:
                    listing = await build_listing(make, model, ad)  # ✅ Fungerer!
                    await queue.put(listing)
                    makeAdsCount += 1
                    totalAdsScraped += 1
                
                page += 1
        
        makeElapsed = time.time() - makeStartTime
        makeRate = makeAdsCount / makeElapsed if makeElapsed > 0 else 0
        print(f" ✅ {makeAdsCount} ads in {makeElapsed:.1f}s ({makeRate:.1f} ads/sec)")
    
    overallElapsed = time.time() - overallStartTime
    print(f"✅ PRODUCER COMPLETED: {totalAdsScraped} ads in {overallElapsed:.1f}s")
    
    await queue.put(None)  # ✅ Signalerer slutt

async def build_listing(make, model, ad):
    coordinates = ad.get("coordinates", {})  # Få coordinates objekt eller tomt som standard
    latitude = coordinates.get("lat")
    longitude = coordinates.get("lon")
    dealerSegmentId = FindDealerSegmentId(ad.get("dealer_segment"))
    organisationName = ad.get("organisation_name") if ad else None
    imageLink=ad.get("image", {}).get("url")

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
        latitude=latitude,
        longitude=longitude,
        image=imageLink,
        timestamp=ad.get("timestamp"),
        status="Sold" if "sold" in ad.get("flags", []) else "Available",
        dealerSegmentId = dealerSegmentId,
        organisationName=organisationName

    )

async def UpdateVinFromApi(session):
    async with db_connection() as conn:
        async with conn.cursor() as cursor:
            cars = await FindCarsForUpdateOfVin(cursor)
            for car_id, regno in cars:
                car_details = {
                    "RegNr": regno,
                    "car_id": car_id
                }
 
                await GetUnderstellsnummerFromRegNr(car_details)
                if car_details is None or car_details["VIN"] is None:
                    print(f"❌ No VIN found for Car ID: {car_id}, skipping...")
                    continue
                else:
                    await UpdateVinOnCars(cursor, car_details)
                    await conn.commit()


async def TransferSoldCarsInCars(session):
    """
    Checks existing cars for sold status and transfers to inactive table.
    Stops immediately if Vegvesen API rate limit (429) is hit.
    Uses automatic batch progression tracking to systematically work through 600k backlog.
    
    Flow:
    1. Read last_processed_car_id from tracking table (where to continue)
    2. Fetch next 20k cars with car_id > last_processed_car_id
    3. Process each car (check FINN.no + Vegvesen API)
    4. Track highest car_id encountered in batch
    5. Save progress (highest car_id) to tracking table
    6. Next run automatically continues from saved position
    
    Progress tracking enables:
    - Automatic continuation through 600k backlog (no manual id > 595000 edits!)
    - Crash recovery (resumes from last saved car_id)
    - Progress monitoring (can query tracking table for statistics)
    
    @param session: aiohttp ClientSession for HTTP requests
    @return: None
    @throws: aiosqlite.Error on database failures, VegvesenRateLimitError on 429
    @author: GitHub Copilot
    """
    import time
    from dbFunctions import update_status_check_progress
    
    startTime = time.time()
    processedCount = 0
    movedToInactive = 0
    finnApiErrors = 0
    vegvesenApiErrors = 0
    skippedCars = 0
    rateLimitHit = False
    highestCarId = 0  # ✅ Track highest car_id in batch
    
    print(f"\n{'='*60}")
    print(f"🔍 STATUS UPDATER STARTED - Checking for sold cars")
    print(f"{'='*60}\n")
    
    async with db_connection() as conn:
        async with conn.cursor() as cursor:
            try:
                # ✅ Fetch next batch using dynamic progress tracking
                cars = await FindCarsForUpdateOfStatus(cursor)
                totalCars = len(cars)
                
                if totalCars == 0:
                    print("✅ No more cars to check! Backlog cleared!")
                    print(f"{'='*60}\n")
                    return
                
                # ✅ Show batch info
                if cars:
                    minCarId = cars[0][0]
                    maxCarId = cars[-1][0]
                    print(f"📊 Processing batch of {totalCars} cars (car_id range: {minCarId} to {maxCarId})\n")
                
                # ✅ WRAP MAIN LOOP IN TRY-EXCEPT FOR RATE LIMIT HANDLING
                try:
                    for car_id, vin, regno, timestamp in cars:
                        car_id = int(car_id)  # ✅ Convert string → int
                        if car_id > highestCarId:  # ✅ Now works: 12345 > 0
                            highestCarId = car_id
                        
                        statusdata = await get_statusdata_on_car(cursor, session, car_id)
                        if statusdata == "404_NOT_FOUND":
                            now = get_timestamp()
                            await move_car_to_inactive(car_id, now)
                            movedToInactive += 1
                            processedCount += 1
                            continue

                        if statusdata is None:
                            finnApiErrors += 1
                            skippedCars += 1
                            processedCount += 1
                            continue

                        date_string = statusdata[1] if len(statusdata) > 1 and statusdata[1] is not None else None
                        converted_date = None
                        
                        if date_string:
                            try:
                                converted_date = convert_date_format_fra_annonse(date_string)
                            except (ValueError, TypeError) as e:
                                skippedCars += 1
                                processedCount += 1
                                continue

                        car_details = {
                            "RegNr": regno,
                            "id": car_id,
                            "VIN": vin,
                            "Timestamp": timestamp,
                            "registrert_forstegang_pa_eierskap": None,
                            "status": statusdata[0],
                            "datoSistEndretAnnonse": converted_date
                        }

                        # ✅ THIS MIGHT RAISE VegvesenRateLimitError!
                        apiErrors = await get_details_from_VVAPI(vin, regno, car_details)
                        vegvesenApiErrors += apiErrors

                        registrert_dato = convert_iso_to_standard_format(car_details.get("registrert_forstegang_pa_eierskap"))

                        sold_date = None
                        
                        if car_details["status"] == "Inaktiv":
                            if registrert_dato and registrert_dato > timestamp:
                                sold_date = registrert_dato
                            else:
                                skippedCars += 1
                                processedCount += 1
                                continue
                        elif car_details["status"] == "SOLGT":
                            if not registrert_dato or registrert_dato <= timestamp:
                                skippedCars += 1
                                processedCount += 1
                                continue
                            sold_date = registrert_dato or car_details["datoSistEndretAnnonse"]

                        if sold_date is None:
                            skippedCars += 1
                            processedCount += 1
                            continue
                        
                        await move_car_to_inactive(car_details["id"], sold_date)
                        movedToInactive += 1
                        processedCount += 1
                        
                        if processedCount % 50 == 0:
                            elapsed = time.time() - startTime
                            rate = processedCount / elapsed if elapsed > 0 else 0
                            finnErrorRate = (finnApiErrors / processedCount * 100) if processedCount > 0 else 0
                            vegvesenErrorRate = (vegvesenApiErrors / (processedCount * 2) * 100) if processedCount > 0 else 0
                            print(f"📊 Progress: {processedCount}/{totalCars} cars ({rate:.1f} cars/sec)")
                            print(f"   Moved: {movedToInactive}, Skipped: {skippedCars}")
                            print(f"   FINN errors: {finnApiErrors} ({finnErrorRate:.1f}%), Vegvesen errors: {vegvesenApiErrors} ({vegvesenErrorRate:.1f}%)")

                # ✅ CATCH RATE LIMIT EXCEPTION
                except VegvesenRateLimitError as e:
                    rateLimitHit = True
                    print(f"\n⚠️ RATE LIMIT HIT: {e}")
                    print(f"⏸️ STATUS UPDATER stopped after processing {processedCount}/{totalCars} cars")
                    print(f"⏰ Will resume on next cron run (retry after {e.retryAfter} seconds)")
                
                # ✅ SAVE PROGRESS AFTER BATCH (even if rate limit hit!)
                if highestCarId > 0:
                    await update_status_check_progress(cursor, highestCarId, processedCount)
                    await conn.commit()
                    print(f"\n✅ Progress saved: last_processed_car_id = {highestCarId}")
                    print(f"   Next run will start from: car_id > {highestCarId}")

            except Exception as e:
                print(f"❌ Fatal error in status updater: {e}")
                import traceback
                print(f"Full error traceback: {traceback.format_exc()}")
                return
    
    totalElapsed = time.time() - startTime
    overallRate = processedCount / totalElapsed if totalElapsed > 0 else 0
    finnErrorRate = (finnApiErrors / processedCount * 100) if processedCount > 0 else 0
    vegvesenErrorRate = (vegvesenApiErrors / (processedCount * 2) * 100) if processedCount > 0 else 0
    
    print(f"\n{'='*60}")
    if rateLimitHit:
        print(f"⏸️ STATUS UPDATER PAUSED (Rate Limit)")
    else:
        print(f"✅ STATUS UPDATER COMPLETED")
    print(f"   Batch processed: {processedCount}/{totalCars}")
    print(f"   Moved to inactive: {movedToInactive}")
    print(f"   Skipped: {skippedCars}")
    print(f"   Highest car_id processed: {highestCarId}")
    print(f"   FINN.no API errors: {finnApiErrors} ({finnErrorRate:.1f}%)")
    print(f"   Vegvesen API errors: {vegvesenApiErrors} ({vegvesenErrorRate:.1f}%)")
    print(f"   Time: {totalElapsed:.1f}s")
    print(f"   Rate: {overallRate:.1f} cars/sec")
    print(f"{'='*60}\n")

async def get_details_from_VVAPI(vin, regno, car_details):
    """
    Fetches vehicle details from Vegvesen API using VIN or RegNo.
    Handles multiple response formats (kjoretoyId dict, arrays, strings).
    Distinguishes between "not found" and "not registered yet" scenarios.
    Raises VegvesenRateLimitError on 429 to allow different handling strategies.
    
    @param vin: Vehicle Identification Number (str or None)
    @param regno: Registration number (str or None)
    @param car_details: Dictionary to update with fetched data (dict)
    @return: Number of API errors encountered (int)
    @throws: VegvesenRateLimitError when API rate limit (429) is hit
    @author: GitHub Copilot
    """
    errorCount = 0
    hasValidVin = vin and is_valid_vin(vin)
    hasValidRegno = regno and is_valid_regno(regno)
    
    def is_429_error(resultat):
        """
        Checks if response is HTTP 429 rate limit error.
        
        @param resultat: API response dictionary (dict)
        @return: True if 429 error, False otherwise (bool)
        @throws: None
        @author: GitHub Copilot
        """
        return isinstance(resultat, dict) and resultat.get("feil") == "HTTP error 429"
    
    def extract_value(kjoretoy, key):
        """
        Extracts value from multiple possible locations in Vegvesen API response.
        Handles three formats: kjoretoyId dict, top-level arrays, top-level strings.
        
        @param kjoretoy: Vehicle data object from API response (dict)
        @param key: Key to extract - 'kjennemerke', 'understellsnummer', etc. (str)
        @return: Extracted value or None if not found (str or None)
        @throws: None
        @author: GitHub Copilot
        """
        if 'kjoretoyId' in kjoretoy:
            kjoretoyId = kjoretoy.get('kjoretoyId')
            if isinstance(kjoretoyId, dict) and key in kjoretoyId:
                value = kjoretoyId.get(key)
                if value:
                    return value
        
        if key in kjoretoy:
            value = kjoretoy.get(key)
            
            if isinstance(value, list) and len(value) > 0:
                return value[0]
            
            if isinstance(value, str) and value:
                return value
        
        return None
    
    def check_empty_registration(resultat):
        """
        Checks if response indicates vehicle exists but is not registered yet.
        Returns True if vehicle found in system but has empty kjennemerke array.
        This is normal for newly imported vehicles awaiting registration.
        
        @param resultat: API response dictionary (dict or None)
        @return: True if unregistered vehicle, False otherwise (bool)
        @throws: None
        @author: GitHub Copilot
        """
        if not isinstance(resultat, dict):
            return False
        
        if 'kjoretoydataListe' not in resultat:
            return False
        
        kjoretoydataListe = resultat.get('kjoretoydataListe')
        if not kjoretoydataListe or len(kjoretoydataListe) == 0:
            return False
        
        kjoretoy = kjoretoydataListe[0]
        
        if 'kjennemerke' in kjoretoy:
            kjennemerke = kjoretoy.get('kjennemerke')
            if isinstance(kjennemerke, list) and len(kjennemerke) == 0:
                return True
        
        return False

    def valid_result(resultat, key):
        """
        Validates Vegvesen API response structure and checks if requested key exists.
        Handles multiple response formats from Vegvesen API.
        
        Validation order (important!):
        1. Null check
        2. String error check
        3. HTTP 429 check (raises exception!)
        4. Other error checks
        5. Structure validation (kjoretoydataListe)
        6. Key existence check (multiple locations)
        
        @param resultat: API response dictionary (or None/string on error)
        @param key: Key to look for in vehicle data (str)
        @return: True if valid data with requested key found, False otherwise (bool)
        @throws: VegvesenRateLimitError on 429 errors
        @author: GitHub Copilot
        """
        if not resultat:
            return False
        
        if resultat == "Request failed":
            return False
        
        if is_429_error(resultat):
            retryAfter = resultat.get("retry_after", 3600)
            raise VegvesenRateLimitError(
                f"Vegvesen API rate limit exceeded. Retry after {retryAfter} seconds.",
                retryAfter=retryAfter
            )
        
        if "feil" in resultat or "error" in resultat:
            return False
        
        if 'kjoretoydataListe' not in resultat:
            return False
        
        kjoretoydataListe = resultat.get('kjoretoydataListe')
        if not kjoretoydataListe or len(kjoretoydataListe) == 0:
            return False
        
        kjoretoy = kjoretoydataListe[0]
        
        if 'kjoretoyId' in kjoretoy:
            kjoretoyId = kjoretoy.get('kjoretoyId')
            if isinstance(kjoretoyId, dict) and key in kjoretoyId:
                value = kjoretoyId.get(key)
                if value:
                    return True
        
        if key in kjoretoy:
            value = kjoretoy.get(key)
            
            if isinstance(value, list):
                if len(value) > 0 and value[0]:
                    return True
            
            elif isinstance(value, str):
                if value:
                    return True
        
        return False

    if hasValidVin:
        parameter = "understellsnummer"
        resultat = await hent_kjoretoydata(parameter, car_details.get("VIN"))
        
        if valid_result(resultat, "kjennemerke"):
            kjoretoy = resultat['kjoretoydataListe'][0]
            car_details["RegNr"] = extract_value(kjoretoy, "kjennemerke")
            car_details["registrert_forstegang_pa_eierskap"] = extract_value(kjoretoy, "registrertForstegangPaEierskap")
            return errorCount
        
        if check_empty_registration(resultat):
            print(f"ℹ️ VIN {vin} found in Vegvesen but not registered yet (no kjennemerke assigned)")
            return errorCount
        
        errorCount += 1

    if hasValidRegno:
        parameter = "kjennemerke"
        resultat = await hent_kjoretoydata(parameter, car_details.get("RegNr"))
        
        if valid_result(resultat, "understellsnummer"):
            kjoretoy = resultat['kjoretoydataListe'][0]
            vin = extract_value(kjoretoy, "understellsnummer")
            print("Hentet understellsnummer fra Kjøretøy-API-et", vin)
            car_details["VIN"] = vin
            car_details["registrert_forstegang_pa_eierskap"] = extract_value(kjoretoy, "registrertForstegangPaEierskap")
            return errorCount
        
        errorCount += 1

    if not hasValidVin and not hasValidRegno:
        return 1

    if errorCount > 0:
        print(f"❌ Kunne ikke hente gyldige kjøretøydata for VIN: {vin} eller RegNr: {regno}.")
    
    return errorCount

async def main():
    api_url = "https://www.finn.no/mobility/search/api/search/SEARCH_ID_CAR_USED"
    async with aiohttp.ClientSession() as session:
        car_makes = await get_car_makes(session, api_url)
        queue = asyncio.Queue()

        # Kjør både henting og innsats parallelt
        producer = asyncio.create_task(get_car_listings(queue, session, api_url, car_makes))
        consumer = asyncio.create_task(insert_car_and_price(session, queue))
        #TransferSoldCarsInCars_updater = asyncio.create_task(TransferSoldCarsInCars(session))
        
        #reg_updater = asyncio.create_task(UpdateReg(session))  # ✅ Legger til VIN-oppdateringen
        #vin_updater = asyncio.create_task(UpdateVinFromApi(session))  # ✅ Legger til VIN-oppdateringen
        await producer  # Venter på at produsenten skal avslutte
        # Signaliser til konsumerende task (en gang er nok)
        await queue.put(None)

        await consumer  # Vent på at konsumeren er ferdig
        #await reg_updater  # Vent på at VIN-oppdateringen er ferdig
        #await vin_updater  # Vent på at VIN-oppdateringen er ferdig
        #await TransferSoldCarsInCars_updater
        
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
