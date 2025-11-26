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
from dataclasses import dataclass
from dbFunctions import  UpdateModelNoOnCars, FindCarsForUpdateOfStatus, UpdateFreeTextOnCars, FindCarsForUpdateOfFreetext, UpdateVinOnCars, UpdateRegNoOnInactiveCars, FindCarsForUpdateOfVin, FindCarsForUpdateOfRegNo, UpdateVinOnInactiveCar, move_car_to_inactive, verify_inactive_car, get_current_price, insert_price, does_car_id_exist, insert_car
from KjoretoyAPI import hent_kjoretoydata
import locale
from dateUtils import (
    convert_date_format_fra_annonse,
    convert_iso_to_standard_format,
)

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
}
max_attempts = 3
db_write_lock = asyncio.Lock()

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

    car.vin = car_details.get("VIN") if car_details else None
    car.model = car_details.get("Modell") if car_details else car.model
    car.gearbox = car_details.get("Girkasse") if car_details else None
    car.fuel = car_details.get("Drivstoff") if car_details else None
    
    await insert_car(cursor, car, now)
    await insert_price(cursor, car.id, car.price, now)

async def GetUnderstellsnummerFromRegNr(car_details):
    parameter = "kjennemerke"  # eller "understellsnummer"
    resultat  = await hent_kjoretoydata(parameter, car_details.get("RegNr"))
        # Sjekk om resultatet er gyldig og inneholder "understellsnummer"
    if resultat and "understellsnummer" in resultat:
        car_details["VIN"] = resultat["understellsnummer"]
        print("Hentet understellsnummer fra Kjøretøy-API-et", car_details["VIN"])
    else:
        car_details["VIN"] = None  # eller en standardverdi
        print("Kunne ikke hente understellsnummer", car_details["car_id"])

async def GetRegNrFromUnderstellsnummer(car_details):
    parameter = "understellsnummer"
    resultat  = await hent_kjoretoydata(parameter, car_details.get("VIN"))
        # Sjekk om resultatet er gyldig og inneholder "understellsnummer"
    if resultat and "kjennemerke" in resultat:
        car_details["RegNr"] = resultat["kjennemerke"]
        print("Hentet kjennemerke fra Kjøretøy-API-et", car_details["RegNr"])
    else:
        car_details["RegNr"] = None  # eller en standardverdi
        print("Kunne ikke hente kjennemerke", car_details["car_id"])

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
                return None
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
            print(f"❌ Error during request to {url}: {e}")
            if attempt < max_attempts:
                print(f"Retrying ({attempt}/{max_attempts})...")
                await asyncio.sleep(5)
            else:
                print(f"❌ Max retries reached for {url}. Giving up.")
                return None

async def get_statusdata_on_car(cursor, session, car_id):
        url = 'https://www.finn.no/car/used/ad.html?finnkode=' + str(car_id)
       
        response_text = await fetch_with_retry(url, session, parse_json=False, max_attempts=3)
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
            sist_endret_p = overordnet_div.find('p', class_='s-text-subtle mb-0', text='Sist endret')
            
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
                print("Elementet med 'Sist endret' ble ikke funnet.")
                dato = None  # ✅ Set default value when "Sist endret" paragraph is not found
        else:
            print("Overordnet <div>-element ble ikke funnet.")
            dato = None  # ✅ Set default value when main div is not found

        return status, dato

async def get_extended_car_data(cursor, session, car_id):
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
            description = soup.find('p', class_='s-text-subtle').text
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
            'car_id': car_id,
            'imageLink': imageLink,
            'freeTextModel': freeTextModel
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
        if response_data is None:
            return []
        return response_data.get("docs", [])
    
async def get_car_listings(queue, session, base_url, makes):
    
    semaphore = asyncio.Semaphore(20)  # Begrens til maksimum 20 samtidige forespørsel
    for make in makes:
        print(f"Bilmerke: {make['make_name']} (Value: {make['make_value']})")
        
        for model in make['models']:
            page = 1
            while True:
                url = f"{base_url}?model={model['model_value']}&page={page}&sales_form=1"
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
    async with db_connection() as conn:
        async with conn.cursor() as cursor:
            try:
                cars = await FindCarsForUpdateOfStatus(cursor)
                for car_id, vin, regno, timestamp in cars:
                    statusdata = await get_statusdata_on_car(cursor, session, car_id)
                    if statusdata is None:
                        continue

                    car_details = {
                        "RegNr": regno,
                        "id": car_id,
                        "VIN": vin,
                        "Timestamp": timestamp,
                        "registrert_forstegang_pa_eierskap": None,
                        "status": statusdata[0],
                        "datoSistEndretAnnonse": convert_date_format_fra_annonse(statusdata[1])
                    }

                    await get_details_from_VVAPI(vin, regno, car_details)

                    registrert_dato = convert_iso_to_standard_format(car_details.get("registrert_forstegang_pa_eierskap"))

                    if car_details["status"] == "Inaktiv":
                        if registrert_dato and registrert_dato > timestamp:
                            sold_date = registrert_dato
                        elif registrert_dato and registrert_dato < timestamp:
                            continue
                        else:
                            continue
                    elif car_details["status"] == "SOLGT":
                        if (registrert_dato is None) or (registrert_dato == ""):
                            #vraket?
                            print(f"❌ Vraket eller avregistert? Car ID: {car_id}, skipping...")
                            continue
                        if (registrert_dato <= timestamp):
                            #ikke solgt
                            continue
                        sold_date = registrert_dato or car_details["datoSistEndretAnnonse"]

                    if sold_date is None:
                        print(f"❌ Ingen gyldig dato funnet for Car ID: {car_id}, skipping...")
                        continue
                    await move_car_to_inactive(car_details["id"], sold_date)

            except Exception as e:
                print(f"En feil oppstod under overføring av solgte biler: {e}")

async def get_details_from_VVAPI(vin, regno, car_details):
    def is_429_error(resultat):
        return isinstance(resultat, dict) and resultat.get("feil") == "HTTP error 429"

    def valid_result(resultat, key):
        if not resultat:
            return False
        if resultat == "Request failed":
            return False
        if is_429_error(resultat):
            print("HTTP error 429: Too Many Requests. Avslutter funksjonen.")
            return None  # None betyr: avslutt funksjonen
        if "feil" in resultat or "error" in resultat:
            return False
        if key not in resultat or not resultat.get(key):
            return False
        return True

    # Prøv VIN først hvis tilgjengelig
    if vin:
        parameter = "understellsnummer"
        resultat = await hent_kjoretoydata(parameter, car_details.get("VIN"))
        valid = valid_result(resultat, "kjennemerke")
        if valid is None:
            return  # 429 error, avslutt
        if valid:
            car_details["RegNr"] = resultat.get("kjennemerke")
            car_details["registrert_forstegang_pa_eierskap"] = resultat.get("registrertForstegangPaEierskap")
            return
        # Hvis ikke gyldig, prøv regno hvis mulig

    # Prøv RegNr hvis tilgjengelig og ikke "UREGISTRERT"
    if regno and regno != "UREGISTRERT":
        parameter = "kjennemerke"
        resultat = await hent_kjoretoydata(parameter, car_details.get("RegNr"))
        valid = valid_result(resultat, "understellsnummer")
        if valid is None:
            return  # 429 error, avslutt
        if valid:
            print("Hentet understellsnummer fra Kjøretøy-API-et", resultat.get("understellsnummer"))
            car_details["VIN"] = resultat.get("understellsnummer")
            car_details["registrert_forstegang_pa_eierskap"] = resultat.get("registrertForstegangPaEierskap")
            return

    # Hvis ingen gyldig respons
    print(f"❌ Kunne ikke hente gyldige kjøretøydata for VIN: {vin} eller RegNr: {regno}.")

async def main():
    api_url = "https://www.finn.no/mobility/search/api/search/SEARCH_ID_CAR_USED"
    async with aiohttp.ClientSession() as session:
        car_makes = await get_car_makes(session, api_url)
        queue = asyncio.Queue()

        # Kjør både henting og innsats parallelt
        producer = asyncio.create_task(get_car_listings(queue, session, api_url, car_makes))
        consumer = asyncio.create_task(insert_car_and_price(session, queue))
        TransferSoldCarsInCars_updater = asyncio.create_task(TransferSoldCarsInCars(session))
        #reg_updater = asyncio.create_task(UpdateReg(session))  # ✅ Legger til VIN-oppdateringen
        #vin_updater = asyncio.create_task(UpdateVinFromApi(session))  # ✅ Legger til VIN-oppdateringen
        await producer  # Venter på at produsenten skal avslutte
        # Signaliser til konsumerende task (en gang er nok)
        await queue.put(None)

        await consumer  # Vent på at konsumeren er ferdig
        #await reg_updater  # Vent på at VIN-oppdateringen er ferdig
        #await vin_updater  # Vent på at VIN-oppdateringen er ferdig
        await TransferSoldCarsInCars_updater
        
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
