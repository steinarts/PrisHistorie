import sqlite3

def update_timestamps_from_prices(db_path):
    # Koble til databasen
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Hent alle ID-er fra cars som mangler timestamp, og finn tidligste dato fra prices
    cursor.execute("""
       SELECT c.id, MIN(p.timestamp) AS earliest_price_date
        FROM inactivecars c
        INNER JOIN prices p ON c.car_id = p.car_id
        WHERE c.timestamp IS NULL 
        GROUP BY c.id    """)
    records = cursor.fetchall()

    # Oppdater timestamp i cars basert på tidligste dato fra prices
    for cId, earliest_price_date in records:
        if earliest_price_date:  # Sjekk at det finnes en dato
            cursor.execute("UPDATE inactivecars SET timestamp = ? WHERE id = ?", (earliest_price_date, cId))

    # Lagre endringene og lukk tilkoblingen
    conn.commit()
    conn.close()
    print("Timestamps oppdatert basert på prices-tabellen.")

# Kjør funksjonen
if __name__ == "__main__":
    db_path = "data/PrisHistorie.db"  # Oppdater med riktig databasebane
    update_timestamps_from_prices(db_path)