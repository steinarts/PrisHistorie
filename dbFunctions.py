import os
from contextlib import asynccontextmanager, contextmanager

import psycopg


def get_db_dsn():
    dsn = os.environ.get("PG_DSN")
    if not dsn:
        raise RuntimeError("PG_DSN is not set. Example: postgresql://prishistorie:devpassword@localhost:5434/prishistorie")
    return dsn


@contextmanager
def db_connection():
    with psycopg.connect(get_db_dsn()) as conn:
        yield conn


@asynccontextmanager
async def db_connection_async():
    async with await psycopg.AsyncConnection.connect(get_db_dsn()) as conn:
        yield conn


async def findOrCreateBodyTypeId(cursor, bodyType):
    """
    Finner eller oppretter en karosseritype i PostgreSQL.
    """
    if bodyType is None or str(bodyType).strip() == "":
        return None

    bodyTypeClean = str(bodyType).strip()

    await cursor.execute(
        "SELECT id FROM body_type WHERE body_type = %s",
        (bodyTypeClean,),
    )
    result = await cursor.fetchone()
    if result:
        return result[0]

    await cursor.execute(
        """
        INSERT INTO body_type (body_type)
        VALUES (%s)
        ON CONFLICT (body_type) DO NOTHING
        RETURNING id
        """,
        (bodyTypeClean,),
    )
    result = await cursor.fetchone()
    if result and result[0] is not None:
        return result[0]

    await cursor.execute(
        "SELECT id FROM body_type WHERE body_type = %s",
        (bodyTypeClean,),
    )
    result = await cursor.fetchone()
    return result[0] if result else None


def normalize_fuel_type_id(value):
    if value is None or value == "" or value == 0 or value == "0":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def FindCarsForUpdateOfVin(cursor):
    await cursor.execute(
        "SELECT car_id, model FROM cars WHERE vin = 0 LIMIT 5000"
    )
    rows = await cursor.fetchall()
    return [(row[0], row[1]) for row in rows]


async def UpdateVinOnInactiveCar(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET reg_no = %s,
                image_link = %s,
                free_text_model = %s,
                ad_status = 'inactive',
                ad_status_changed_at = CURRENT_TIMESTAMP
            WHERE car_id = %s
            """,
            (
                car_details.get("RegNr"),
                car_details.get("imageLink"),
                car_details.get("freeTextModel"),
                car_id,
            ),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere {car_id} i cars: {e}")


async def FindCarsForUpdateOfStatus(cursor):
    lastProcessedId = await get_last_processed_car_id(cursor)
    print(f"🔄 Resuming from car_id > {lastProcessedId}")

    await cursor.execute(
        """
        SELECT car_id, vin, reg_no, first_seen_at
        FROM cars
        WHERE (reg_no IS NOT NULL OR (vin IS NOT NULL AND vin != '0'))
          AND first_seen_at IS NOT NULL
          AND car_id > %s
        ORDER BY car_id ASC
        LIMIT 20000
        """,
        (lastProcessedId,),
    )
    rows = await cursor.fetchall()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def get_last_processed_car_id(cursor):
    await cursor.execute(
        "SELECT last_processed_car_id FROM status_check_progress WHERE id = 1"
    )
    result = await cursor.fetchone()
    return result[0] if result else 0


async def update_status_check_progress(cursor, highestCarId, carsProcessed):
    await cursor.execute(
        """
        UPDATE status_check_progress
        SET last_processed_car_id = %s,
            last_run_timestamp = CURRENT_TIMESTAMP,
            total_cars_processed = total_cars_processed + %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = 1
        """,
        (highestCarId, carsProcessed),
    )


async def get_timestamp_db(cursor):
    await cursor.execute("SELECT CURRENT_TIMESTAMP")
    return (await cursor.fetchone())[0]


async def FindCarsForUpdateOfFreetext(cursor):
    await cursor.execute(
        """
        SELECT car_id
        FROM cars
        WHERE free_text_model IS NULL
          AND image_link IS NULL
        """
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def FindCarsForUpdateOfRegNo(cursor):
    await cursor.execute(
        """
        SELECT car_id
        FROM cars
        WHERE ad_status = 'inactive'
          AND reg_no IS NULL
          AND image_link IS NULL
        """
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def FindCarsForUpdateOfVin(cursor):
    await cursor.execute(
        """
        SELECT car_id, reg_no
        FROM cars
        WHERE ad_status = 'inactive'
          AND vin IS NULL
          AND reg_no IS NOT NULL
        """
    )
    rows = await cursor.fetchall()
    return [(row[0], row[1]) for row in rows]


async def UpdateModelNoOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET reg_no = %s,
                model = %s
            WHERE car_id = %s
            """,
            (car_details.get("RegNr"), car_details.get("Modell"), car_id),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere {car_id} i cars: {e}")


async def UpdateRegNoOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET reg_no = %s,
                image_link = %s
            WHERE car_id = %s
            """,
            (car_details.get("RegNr"), car_details.get("imageLink"), car_id),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere {car_id} i cars: {e}")


async def UpdateVinOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET vin = %s
            WHERE car_id = %s
            """,
            (car_details.get("VIN"), car_id),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere VIN på {car_id} i cars: {e}")


async def UpdateFreeTextOnCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET image_link = %s,
                free_text_model = %s
            WHERE car_id = %s
            """,
            (car_details.get("imageLink"), car_details.get("freeTextModel"), car_id),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere VIN på {car_id} i cars: {e}")


async def UpdateRegNoOnInactiveCars(cursor, car_details):
    try:
        car_id = car_details.get("car_id")
        await cursor.execute(
            """
            UPDATE cars
            SET reg_no = %s,
                image_link = %s,
                free_text_model = %s,
                ad_status = 'inactive'
            WHERE car_id = %s
              AND ad_status = 'inactive'
            """,
            (
                car_details.get("RegNr"),
                car_details.get("imageLink"),
                car_details.get("freeTextModel"),
                car_id,
            ),
        )
    except psycopg.IntegrityError as e:
        print(f"Problemer med å oppdatere VIN på {car_id} i cars: {e}")


async def does_car_id_exist(cursor, car_id):
    await cursor.execute("SELECT car_id FROM cars WHERE car_id = %s LIMIT 1", (car_id,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def insert_car(cursor, car, timestamp):
    try:
        ad_timestamp = car.timestamp
        if isinstance(ad_timestamp, str):
            try:
                ad_timestamp = int(float(ad_timestamp))
            except (TypeError, ValueError):
                ad_timestamp = None

        await cursor.execute(
            """
            INSERT INTO cars (
                car_id, make, model, year, km, gear, fuel_type_id, vin,
                first_seen_at, free_text_model, reg_no, location, url,
                latitude, longitude, image_link, dealer_segment_id,
                organisation_name, ad_timestamp, body_type_id,
                ad_status, ad_status_detail
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', NULL)
            ON CONFLICT (car_id) DO NOTHING
            """,
            (
                car.id,
                car.make,
                car.model,
                car.year,
                car.km,
                car.gearbox,
                normalize_fuel_type_id(car.fuel),
                car.vin,
                timestamp,
                car.heading,
                car.regNo,
                car.location,
                car.url,
                car.latitude,
                car.longitude,
                car.image,
                car.dealerSegmentId,
                car.organisationName,
                ad_timestamp,
                car.bodyTypeId,
            ),
        )
    except psycopg.IntegrityError as e:
        print(f"En bil med ID {car.id} kunne ikke lagres: {e}")


async def insert_price(cursor, car_id, price, timestamp):
    await cursor.execute(
        """
        INSERT INTO prices (car_id, price, timestamp)
        VALUES (%s, %s, %s)
        """,
        (car_id, price, timestamp),
    )


async def verify_inactive_car(cursor, car):
    await cursor.execute(
        "SELECT car_id FROM cars WHERE car_id = %s AND ad_status = 'inactive' LIMIT 1",
        (car.id,),
    )
    return await cursor.fetchone()


async def get_current_price(cursor, car):
    await cursor.execute(
        "SELECT price FROM prices WHERE car_id = %s ORDER BY timestamp DESC LIMIT 1",
        (car.id,),
    )
    return await cursor.fetchone()


async def move_car_to_inactive(car_id, now, detail='legacy_inactive', conn=None, cursor=None):
    if cursor is not None:
        await cursor.execute(
            """
            UPDATE cars
            SET ad_status = 'inactive',
                ad_status_changed_at = %s,
                ad_status_detail = %s
            WHERE car_id = %s
              AND ad_status <> 'inactive'
            """,
            (now, detail, car_id),
        )
        return

    if conn is None:
        async with await psycopg.AsyncConnection.connect(get_db_dsn()) as conn:
            async with conn.cursor() as cursor:
                try:
                    await cursor.execute(
                        """
                        UPDATE cars
                        SET ad_status = 'inactive',
                            ad_status_changed_at = %s,
                            ad_status_detail = %s
                        WHERE car_id = %s
                          AND ad_status <> 'inactive'
                        """,
                        (now, detail, car_id),
                    )
                    await conn.commit()
                except psycopg.IntegrityError as e:
                    print(f"En integritetsfeil oppstod under markering av bil med ID {car_id} som inaktiv: {e}")
                    await conn.rollback()
                except Exception as e:
                    print(f"En uventet feil oppstod under markering av bil med ID {car_id} som inaktiv: {e}")
                    await conn.rollback()
        return

    try:
        await cursor.execute(
            """
            UPDATE cars
            SET ad_status = 'inactive',
                ad_status_changed_at = %s,
                ad_status_detail = %s
            WHERE car_id = %s
              AND ad_status <> 'inactive'
            """,
            (now, detail, car_id),
        )
    except psycopg.IntegrityError as e:
        print(f"En integritetsfeil oppstod under markering av bil med ID {car_id} som inaktiv: {e}")
        await conn.rollback()
    except Exception as e:
        print(f"En uventet feil oppstod under markering av bil med ID {car_id} som inaktiv: {e}")
        await conn.rollback()


async def get_timestamp_db(cursor):
    await cursor.execute("SELECT CURRENT_TIMESTAMP")
    return (await cursor.fetchone())[0]
