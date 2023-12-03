from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tillater alle opprinnelser
    allow_credentials=True,
    allow_methods=["*"],  # Tillater alle metoder
    allow_headers=["*"],  # Tillater alle headere
)

class PriceRequest(BaseModel):
    car_id: int

@app.post("/")
async def index(request: PriceRequest):
    car_id = request.car_id
    price_data = get_price_data(car_id)
    return {"price_data": price_data}
    
def get_price_data(car_id):
    # Koble til SQLite-databasen
    conn = sqlite3.connect("PrisHistorie.db")
    cursor = conn.cursor()

    # Hent prisdata for den angitte bil-IDen
    cursor.execute("SELECT timestamp, price FROM prices WHERE car_id=?", (car_id,))
    price_data = cursor.fetchall()
    # Lukk databasetilkoblingen
    conn.close()

    return price_data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)