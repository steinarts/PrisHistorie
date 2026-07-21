import sqlite3

def expand_tables():
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    # Legg til kolonner i `cars`
    try:
        c.execute("CREATE INDEX idx_cars_car_id ON cars(car_id);")
        c.execute("CREATE INDEX idx_inactivecars_car_id ON inactivecars(car_id);")
        c.execute("CREATE INDEX idx_prices_car_id ON prices(car_id);")
    
    except sqlite3.OperationalError as e:
        print(f"problem med å legge inn indexer: {e}")


import sqlite3

def migrate_database():
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    # Opprett midlertidige tabeller
    c.execute('''
        CREATE TEMP TABLE temp_inactivecarsTSUpdate AS
        SELECT p.car_id, p.timestamp
        FROM prices p 
        WHERE p.price = 9
        AND p.car_id IN (
            SELECT p.car_id 
            FROM prices p 
            JOIN inactivecars i ON p.car_id = i.car_id
            WHERE p.price = 9
        );
    ''')

    c.execute('''
        CREATE TEMP TABLE temp_EarliestPriceTimestamp AS
        SELECT car_id, MIN(timestamp) AS earliest_timestamp
        FROM prices
        GROUP BY car_id
        HAVING MIN(price) = 9;
    ''')

    # Oppdater inactivecars
    c.execute('''
        UPDATE inactivecars
        SET inactivated_timestamp = (
            SELECT timestamp 
            FROM temp_inactivecarsTSUpdate 
            WHERE temp_inactivecarsTSUpdate.car_id = inactivecars.car_id
        ),
        timestamp = (
            SELECT earliest_timestamp
            FROM temp_EarliestPriceTimestamp e
            WHERE e.car_id = inactivecars.car_id
        )
        WHERE car_id IN (
            SELECT car_id 
            FROM temp_inactivecarsTSUpdate
        );
    ''')

    # Slett fra prices
    c.execute('''
        DELETE FROM prices
        WHERE price = 9
        AND car_id IN (
            SELECT car_id 
            FROM temp_inactivecarsTSUpdate
        );
    ''')

    # Slett midlertidige tabeller
    c.execute('DROP TABLE temp_inactivecarsTSUpdate;')
    c.execute('DROP TABLE temp_EarliestPriceTimestamp;')

    conn.commit()
    conn.close()

# Kall funksjonen for å utføre migrasjonen
expand_tables()
migrate_database()





