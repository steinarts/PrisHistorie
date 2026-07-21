import sqlite3
from contextlib import contextmanager
from contextlib import asynccontextmanager
from requests.exceptions import ConnectTimeout
import aiohttp
import asyncio
import aiosqlite

@contextmanager
def db_connection():
    conn = sqlite3.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        conn.close()

@asynccontextmanager 
async def db_connection():
    conn = await aiosqlite.connect('data/PrisHistorie.db', check_same_thread=False)
    try:
        yield conn
    finally:
        await conn.close()

async def findOrCreateBodyTypeId(cursor, bodyType):
    """
    Finner eller oppretter en karosseritype i databasen.
    
    Dette er et klassisk "lookup or insert" mønster som:
    1. Sjekker om karosseritypen allerede eksisterer
    2. Oppretter en ny rad hvis den ikke finnes
    3. Returnerer ID-en for bruk som foreign key i cars-tabellen
    
    @param cursor: Database cursor for asynkrone operasjoner
    @param bodyType: Karosseritype som streng (f.eks. 'Sedan', 'SUV', 'Stasjonsvogn')
    @return: ID for karosseritypen (int), eller None hvis bodyType er ugyldig
    @throws: sqlite3.Error ved databasefeil
    """
    if bodyType is None or bodyType.strip() == "":
        return None

    bodyTypeClean = bodyType.strip()

    await cursor.execute("SELECT id FROM BodyType WHERE BodyType = ?", (bodyTypeClean,))
    result = await cursor.fetchone()

    if result:
        return result[0]
    else:
        await cursor.execute("INSERT INTO BodyType (BodyType) VALUES (?)", (bodyTypeClean,))
        return cursor.lastrowid
    
async def FindCarsForUpdateOfVin(cursor):
    await cursor.execute("SELECT car_id, model FROM cars WHERE vin = 0 LIMIT 5000")
    rows = await cursor.fetchall()
    # Returner en liste av dictionaryer med car_id og model
    return [(row[0], row[1]) for row in rows]

async def  UpdateVinOnInactiveCar(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        #if car_details.get("Kilometerstand") is not None:
        #    kmstand = int(car_details.get("Kilometerstand").replace('\xa0', '').replace(' km', ''))
        #else:
        #    kmstand = 0

        await cursor.execute("""
            UPDATE Inactivecars SET regNo = ?, 
                    imagelink = ?, freeTextModel = ?
            WHERE car_id = ? 
        """, (
            car_details.get("RegNr"),
            car_details.get("imageLink"), car_details.get("freeTextModel"), car_id
        ))


    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere {car_id} i cars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)


async def FindCarsForUpdateOfStatus(cursor):
    # ✅ Read last processed ID from tracking table
    lastProcessedId = await get_last_processed_car_id(cursor)
    
    print(f"🔄 Resuming from car_id > {lastProcessedId}")
    
    await cursor.execute("""
        SELECT car_id, vin, regno, timestamp
        FROM cars
        WHERE (regno IS NOT NULL OR (vin IS NOT NULL AND vin != '0'))
        AND timestamp IS NOT NULL
        AND car_id > ?  
        ORDER BY car_id ASC  
        LIMIT 20000                         
    """, (lastProcessedId,))
    
    rows = await cursor.fetchall()
    # Returner en liste av dictionaryer med car_id, vin, regno
    return [(row[0], row[1], row[2], row[3]) for row in rows]

async def get_last_processed_car_id(cursor):
    """
    Retrieves the last processed car_id from tracking table.
    Used by FindCarsForUpdateOfStatus to determine where to continue processing.
    
    This function is the "reader" in our progress tracking system. It queries
    the single-row tracking table to find out which car_id was last successfully
    processed, allowing automatic resumption without manual intervention.
    
    @param cursor: aiosqlite cursor for database operations
    @return: Last processed car_id (int), or 0 if no progress exists
    @throws: sqlite3.Error on database failures
    @author: GitHub Copilot
    """
    await cursor.execute("""
        SELECT last_processed_car_id 
        FROM status_check_progress 
        WHERE id = 1
    """)
    result = await cursor.fetchone()
    return result[0] if result else 0

async def update_status_check_progress(cursor, highestCarId, carsProcessed):
    """
    Updates the progress tracking table after batch completion.
    Saves highest car_id processed so next run can continue from that point.
    
    This function is the "writer" in our progress tracking system. After processing
    a batch of 20k cars, it saves the highest car_id encountered so the next run
    knows exactly where to resume. Also tracks lifetime statistics for monitoring.
    
    Example usage:
        # After processing batch with car_ids 45893-89234:
        await update_status_check_progress(cursor, 89234, 20000)
        # Next run will automatically start from car_id > 89234
    
    @param cursor: aiosqlite cursor for database operations
    @param highestCarId: Highest car_id processed in this batch (int)
    @param carsProcessed: Number of cars processed in this batch (int)
    @return: None
    @throws: sqlite3.Error on database failures
    @author: GitHub Copilot
    """
    await cursor.execute("""
        UPDATE status_check_progress
        SET last_processed_car_id = ?,
            last_run_timestamp = datetime('now', 'localtime'),
            total_cars_processed = total_cars_processed + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
    """, (highestCarId, carsProcessed))

async def get_timestamp_db(cursor):
    return cursor.execute("SELECT datetime('now', 'localtime')").fetchone()[0]

async def FindCarsForUpdateOfFreetext(cursor):

    await cursor.execute("""
						select car_id from cars
                        where freetextmodel is null
                        and imagelink is NULL
                         """)

    rows = await cursor.fetchall()
    # Returner en liste av dictionaryer med car_id og model
    return [(row[0]) for row in rows]


async def FindCarsForUpdateOfRegNo(cursor):

    await cursor.execute("""
                        select car_id from inactivecars
                        where regno is NULL
                        and imagelink is NULL
                         """)

    rows = await cursor.fetchall()
    # Returner en liste av dictionaryer med car_id og model
    return [(row[0]) for row in rows]

async def FindCarsForUpdateOfVin(cursor):

    await cursor.execute("""
                        select car_id, regno from inactivecars
                        where vin is NULL
                        and regno is not NULL
                         """)

    rows = await cursor.fetchall()
    # Returner en liste av dictionaryer med car_id og model
    return [(row[0], row[1]) for row in rows]

async def UpdateModelNoOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        await cursor.execute("""
            UPDATE cars SET regNo = ?, model = ?
            WHERE car_id = ? 
        """, (car_details.get("RegNr"),  car_details.get("Modell"), car_id
        ))


    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere {car_id} i cars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def UpdateRegNoOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        await cursor.execute("""
            UPDATE cars SET regNo = ?, imagelink = ?
            WHERE car_id = ? 
        """, (car_details.get("RegNr"),  car_details.get("imageLink"), car_id
        ))


    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere {car_id} i cars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def UpdateVinOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        await cursor.execute("""
            UPDATE inactivecars SET vin = ?
            WHERE car_id = ? 
        """, (car_details.get("VIN"),  car_id
        ))


    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere VIN på {car_id} i inactivecars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def UpdateFreeTextOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        await cursor.execute("""
            UPDATE cars SET  imagelink = ?, freeTextModel = ?
            WHERE car_id = ? 
        """, (car_details.get("imageLink"), car_details.get("freeTextModel"), car_id
        ))

    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere VIN på {car_id} i inactivecars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)

async def UpdateRegNoOnInactiveCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        
        await cursor.execute("""
            UPDATE inactivecars SET regno = ?, imagelink = ?, freeTextModel = ?
            WHERE car_id = ? 
        """, (car_details.get("RegNr"),  car_details.get("imageLink"), car_details.get("freeTextModel"), car_id
        ))

    except sqlite3.IntegrityError as e:
        if 'UNIQUE constraint failed: cars.car_id' in str(e):
            print(f"Problemer med å oppdatere VIN på {car_id} i inactivecars.")
        else:
            print("En annen integritetsrelatert feil oppstod:", e)


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
            INSERT INTO cars (car_id, make, model, year, km, gear, fuelTypeId, vin, timestamp,
                              freeTextModel, regNo, location, url, latitude, longitude, imagelink, dealerSegmentId, organisationName, adTimestamp, bodyTypeId)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) 
        """, (
            car.id, car.make, car.model, car.year, car.km, car.gearbox, car.fuel,
            car.vin, timestamp, car.heading, car.regNo, car.location, car.url, car.latitude, 
            car.longitude, car.image, car.dealerSegmentId, car.organisationName, car.timestamp, car.bodyTypeId
        ))
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

async def verify_inactive_car(cursor, car):
    await cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car.id,))
    car_exists = await cursor.fetchone()
    return car_exists

async def get_current_price(cursor, car):
    await cursor.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car.id,))
    price_found = await cursor.fetchone()
    return price_found

async def move_car_to_inactive(car_id, now):
    async with aiosqlite.connect('data/PrisHistorie.db', check_same_thread=False) as conn:
        async with conn.cursor() as cursor:
            try:
                # Sjekk om bilen allerede finnes i inactivecars
                await cursor.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car_id,))
                car_exists = await cursor.fetchone()

                if car_exists:
                    #print(f"Bil med ID {car_id} finnes allerede i inactivecars. Hopper over flytting.")
                    return

                # Flytt bilen til inactivecars
                await cursor.execute("""
                    INSERT INTO inactivecars (car_id, make, model, year, km, gear, fuelTypeId, vin, freeTextModel, regNo, location, url, latitude, longitude, imagelink, 
                                     timestamp, inactivated_timestamp, dealerSegmentId, organisationName, adTimestamp, bodyTypeId)
                    SELECT car_id, make, model, year, km, gear, fuelTypeId, vin, freeTextModel, regNo, location, url, latitude, longitude, imagelink, timestamp, ?, 
                                     dealerSegmentId, organisationName, adTimestamp, bodyTypeId
                    FROM cars WHERE car_id = ?
                """, (now, car_id))

                # Slett bilen fra cars etter vellykket innsats
                await cursor.execute("DELETE FROM cars WHERE car_id = ?", (car_id,))

                # Commit changes
                await conn.commit()

            except sqlite3.IntegrityError as e:
                print(f"En integritetsfeil oppstod under flytting av bil med ID {car_id} til inactivecars: {e}")
                await conn.rollback()
            except Exception as e:
                print(f"En uventet feil oppstod under flytting av bil med ID {car_id} til inactivecars: {e}")
                await conn.rollback()

async def get_timestamp_db(cursor):
    return cursor.execute("SELECT datetime('now', 'localtime')").fetchone()[0]
