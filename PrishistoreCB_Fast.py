from fastapi import FastAPI, Request, Response
import xml.etree.ElementTree as ET
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
import sqlite3
from contextlib import contextmanager
import json

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

@contextmanager
def db_connection():
    conn = sqlite3.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        conn.close()

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
      
    price_data = get_price_data(car_id)
    return {"price_data": price_data}



def get_price_data(car_id):
    # Koble til SQLite-databasen
    with db_connection() as conn:
        cursor = conn.cursor()

        # Hent prisdata for den angitte bil-IDen
        cursor.execute("""
            WITH vin_list AS (
                -- Hent vin-nummeret for car_id = 389224182 fra begge tabeller
                SELECT vin 
                FROM cars 
                WHERE car_id = ?
                UNION 
                SELECT vin 
                FROM inactivecars 
                WHERE car_id = ?
            ),
            car_idList AS (
                -- Hent alle car_id-er som har dette vin-nummeret fra begge tabeller
                SELECT car_id 
                FROM cars 
                WHERE vin IN (SELECT vin FROM vin_list)
                UNION 
                SELECT car_id 
                FROM inactivecars 
                WHERE vin IN (SELECT vin FROM vin_list)
                UNION 
                -- Inkluder den opprinnelige car_id = ? eksplisitt
                SELECT ? AS car_id
            )

            SELECT 
                c.car_id AS current_car_id,
                c.vin,
                p.price,
                c.km,
                p.timestamp AS price_timestamp,
                NULL AS listed_timestamp, -- Alltid NULL for aktive biler
                NULL AS sold_timestamp,   -- Alltid NULL for aktive biler
                NULL AS days_listed       -- Alltid NULL for aktive biler
            FROM 
                cars c
            JOIN 
                prices p ON c.car_id = p.car_id
            WHERE 
                c.car_id IN (SELECT car_id FROM car_idList)
                       
            UNION
                       
            SELECT 
                ic.car_id AS inactive_car_id,
                ic.vin,
                p.price,
                ic.km,
                p.timestamp AS price_timestamp,
                ic.timestamp AS listed_timestamp,
                ic.inactivated_timestamp AS sold_timestamp,
                CAST(JULIANDAY(ic.inactivated_timestamp) - JULIANDAY(ic.timestamp) AS INTEGER) AS days_listed
            FROM 
                inactivecars ic
            JOIN 
                prices p ON ic.car_id = p.car_id
            WHERE 
                ic.car_id IN (SELECT car_id FROM car_idList)

            ORDER BY 
                price_timestamp;
        """, (car_id, car_id, car_id))
        """cursor.execute("SELECT timestamp, price FROM prices WHERE car_id=?", (car_id,))"""
        price_data = cursor.fetchall()

    return price_data

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

    raw_data = get_new_cars_last_week()
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
        
    json_str = json.dumps({"stats_data": data}, ensure_ascii=False)
    return Response(content=json_str, media_type="application/json")
    

def get_new_cars_last_week():
    # Koble til SQLite-databasen
    with db_connection() as conn:
        cursor = conn.cursor()

        # Henter stats for nye biler lagt til i løpet av den siste uken
        cursor.execute("""SELECT 
                        DATE(timestamp) AS Date,
                        COUNT(CASE 
                            WHEN TIME(timestamp) BETWEEN '09:00:00' AND '11:00:00' THEN 1 
                            ELSE NULL 
                        END) AS Count_09_11,
                        COUNT(CASE 
                            WHEN TIME(timestamp) BETWEEN '14:00:00' AND '16:00:00' THEN 1 
                            ELSE NULL 
                        END) AS Count_14_16,
                        COUNT(CASE 
                            WHEN TIME(timestamp) BETWEEN '18:00:00' AND '20:00:00' THEN 1 
                            ELSE NULL 
                        END) AS Count_18_20,
                        COUNT(CASE 
                            WHEN (TIME(timestamp) >= '22:00:00' OR TIME(timestamp) < '00:00:00') THEN 1 
                            ELSE NULL 
                        END) AS Count_22_00
                    FROM cars
                    WHERE DATE(timestamp) >= DATE('now', '-7 day')
                    GROUP BY DATE(timestamp)
                    ORDER BY DATE(timestamp) DESC;
                    """)
        price_data = cursor.fetchall()

    return price_data


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)