import sqlite3

# Create a new database file or connect to existing one
conn = sqlite3.connect('PrisHistorie.db')

# Create a cursor
c = conn.cursor()

# Create 'cars' table
c.execute("""
CREATE TABLE IF NOT EXISTS cars (
    id INTEGER PRIMARY KEY,
    car_id TEXT UNIQUE,
    make TEXT,
    model TEXT,
    year INTEGER,
    km INTEGER,
    gear TEXT,
    fuelTypeId INTEGER,
    vin TEXT,
    FOREIGN KEY (fuelTypeId) REFERENCES FuelTypes (id)
)
""")

#create inactivecars
c.execute("""
CREATE TABLE IF NOT EXISTS inactivecars (
    id INTEGER PRIMARY KEY,
    car_id TEXT UNIQUE,
    make TEXT,
    model TEXT,
    year INTEGER,
    km INTEGER,
    gear TEXT,
    fuelTypeId INTEGER,
    vin TEXT,
    FOREIGN KEY (fuelTypeId) REFERENCES FuelTypes (id)
)
""")


# Create 'prices' table
c.execute("""
CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY,
    car_id TEXT,
    price REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (car_id) REFERENCES cars (car_id)
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS FuelTypes (
    id INTEGER PRIMARY KEY,
    type TEXT UNIQUE
)
""")
 
# Insert fuel types
fuel_types = ['Diesel', 'Bensin', 'Hybrid', 'El']
for fuel_type in fuel_types:
    c.execute("SELECT COUNT(*) FROM FuelTypes WHERE type = ?", (fuel_type,))
    count = c.fetchone()[0]
    if count == 0:
        c.execute("INSERT INTO FuelTypes (type) VALUES (?)", (fuel_type,))

# Save (commit) the changes
conn.commit()

# Close the connection
conn.close()
