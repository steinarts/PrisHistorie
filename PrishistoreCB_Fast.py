import asyncio
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI()

logging.basicConfig(level=logging.INFO)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tillater alle opprinnelser
    allow_credentials=True,
    allow_methods=["*"],  # Tillater alle metoder
    allow_headers=["*"],  # Tillater alle headere
)

class PriceRequest(BaseModel):
    car_id: int

@asynccontextmanager
async def db_connection():
    async with await psycopg.AsyncConnection.connect(os.environ["PG_DSN"]) as conn:
        yield conn


@app.get("/CheckServer")
async def root():
    return {"message": "Server is running"}

@app.post("/")
async def index(request: Request, price_request: PriceRequest):
    # Hent data fra PriceRequest-modellen
    car_id = price_request.car_id
    # logging
    client_host = request.client.host
    logging.info(f"Search query: {car_id}, Client IP: {client_host}")
      
    price_data = await get_price_data(car_id)
    return {"price_data": price_data}



async def get_price_data(car_id):
    async with db_connection() as conn:
        async with conn.cursor() as cursor:
            await cursor.execute(
                """
                WITH vin_list AS (
                    SELECT vin
                    FROM cars
                    WHERE car_id = %s
                    UNION
                    SELECT vin
                    FROM cars
                    WHERE car_id = %s AND ad_status = 'inactive'
                ),
                car_id_list AS (
                    SELECT car_id
                    FROM cars
                    WHERE vin IN (SELECT vin FROM vin_list)
                    UNION
                    SELECT %s::bigint AS car_id
                )

                SELECT
                    c.car_id AS current_car_id,
                    c.vin,
                    p.price,
                    c.km,
                    p.timestamp AS price_timestamp,
                    NULL AS listed_timestamp,
                    NULL AS sold_timestamp,
                    NULL AS days_listed
                FROM cars c
                JOIN prices p ON c.car_id = p.car_id
                WHERE c.car_id IN (SELECT car_id FROM car_id_list)
                  AND c.ad_status = 'active'

                UNION ALL

                SELECT
                    c.car_id AS inactive_car_id,
                    c.vin,
                    p.price,
                    c.km,
                    p.timestamp AS price_timestamp,
                    c.first_seen_at AS listed_timestamp,
                    c.ad_status_changed_at AS sold_timestamp,
                    EXTRACT(DAY FROM (c.ad_status_changed_at - c.first_seen_at))::integer AS days_listed
                FROM cars c
                JOIN prices p ON c.car_id = p.car_id
                WHERE c.car_id IN (SELECT car_id FROM car_id_list)
                  AND c.ad_status = 'inactive'

                ORDER BY price_timestamp;
                """,
                (car_id, car_id, car_id),
            )
            return await cursor.fetchall()

def dict_to_xml(tag, d):
    """
    Turn a simple dict of key/value pairs into XML
    """
    elem = ET.Element(tag)
    for key, val in d.items():
        child = ET.SubElement(elem, key)
        if isinstance(val, dict):
            child.extend(dict_to_xml(key, val))
        else:
            child.text = str(val)
    return elem

@app.get("/GetNewCarsLastWeek", response_class=Response)
async def index(request: Request, format: str = "json"):    
    # logging
    client_host = request.client.host
    logging.info(f"GetNewCarsLastWeek, Client IP: {client_host}")

    raw_data = await get_new_cars_last_week()
    # Transform the data into a list of dictionaries
    data = [
        {
            "date": entry[0],
            "time": {
                "0900": entry[1],
                "1400": entry[2],
                "1800": entry[3],
                "2200": entry[4]

            }
        }
        for entry in raw_data
    ]

    if format == "xml":
        root = ET.Element("stats_data")
        for item in data:
            child = dict_to_xml("entry", item)
            root.append(child)
        
        xml_str = ET.tostring(root, encoding='utf-8').decode('utf-8')
        return Response(content=xml_str, media_type="application/xml")
        
    return JSONResponse(content=jsonable_encoder({"stats_data": data}))
    

async def get_new_cars_last_week():
    async with db_connection() as conn:
        logging.info("DATABASE DRIVER: %s", "psycopg")
        logging.info("DATABASE HOST: %s", conn.info.host)
        logging.info("DATABASE PORT: %s", conn.info.port)
        logging.info("DATABASE NAME: %s", conn.info.dbname)

        async with conn.cursor() as cursor:
            await cursor.execute("SELECT current_database(), inet_server_addr(), inet_server_port()")
            logging.info("DATABASE SERVER INFO: %s", await cursor.fetchone())

            await cursor.execute(
                """
                SELECT
                    DATE(first_seen_at AT TIME ZONE 'Europe/Oslo') AS date,
                    COUNT(CASE WHEN EXTRACT(HOUR FROM first_seen_at AT TIME ZONE 'Europe/Oslo') BETWEEN 9 AND 11 THEN 1 END) AS count_09_11,
                    COUNT(CASE WHEN EXTRACT(HOUR FROM first_seen_at AT TIME ZONE 'Europe/Oslo') BETWEEN 14 AND 16 THEN 1 END) AS count_14_16,
                    COUNT(CASE WHEN EXTRACT(HOUR FROM first_seen_at AT TIME ZONE 'Europe/Oslo') BETWEEN 18 AND 20 THEN 1 END) AS count_18_20,
                    COUNT(CASE WHEN EXTRACT(HOUR FROM first_seen_at AT TIME ZONE 'Europe/Oslo') >= 22 OR EXTRACT(HOUR FROM first_seen_at AT TIME ZONE 'Europe/Oslo') < 1 THEN 1 END) AS count_22_00
                FROM cars
                WHERE first_seen_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
                GROUP BY DATE(first_seen_at AT TIME ZONE 'Europe/Oslo')
                ORDER BY DATE(first_seen_at AT TIME ZONE 'Europe/Oslo') DESC
                """
            )
            return await cursor.fetchall()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)