-- LEGACY SQLite schema.
-- Kept for reference during the SQLite -> PostgreSQL migration.
-- Do not use this file to create the PostgreSQL database.
-- BodyType definition

CREATE TABLE BodyType (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                BodyType TEXT NOT NULL UNIQUE
            );


-- DealerSegment definition

CREATE TABLE DealerSegment (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );


-- demo definition

CREATE TABLE demo (ID integer primary key, Name varchar(20), Hint text );


-- FuelTypes definition

CREATE TABLE FuelTypes (
    id INTEGER PRIMARY KEY,
    type TEXT UNIQUE
);


-- status_check_progress definition

CREATE TABLE status_check_progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_processed_car_id INTEGER DEFAULT 0,
                last_run_timestamp TEXT,
                total_cars_processed INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );


-- cars definition

CREATE TABLE cars (
    id INTEGER PRIMARY KEY,
    car_id TEXT UNIQUE,
    make TEXT,
    model TEXT,
    year INTEGER,
    km INTEGER,
    gear TEXT,
    fuelTypeId INTEGER,
    vin TEXT, timestamp DATETIME, freeTextModel Text, regNo TEXT, location TEXT, url TEXT, latitude REAL, longitude REAL, imagelink TEXT, dealerSegmentId TEXT, organisationName TEXT, adTimestamp INTEGER, bodyTypeId 
                     INTEGER REFERENCES BodyType(id),
    FOREIGN KEY (fuelTypeId) REFERENCES FuelTypes (id)
);

CREATE INDEX idx_cars_car_id ON cars(car_id);
CREATE INDEX idx_cars_timestamp 
            ON cars(timestamp)
        ;


-- inactivecars definition

CREATE TABLE inactivecars (
    id INTEGER PRIMARY KEY,
    car_id TEXT UNIQUE,
    make TEXT,
    model TEXT,
    year INTEGER,
    km INTEGER,
    gear TEXT,
    fuelTypeId INTEGER,
    vin TEXT, timestamp DATETIME, freetextmodel Text, regNo TEXT, location TEXT, url TEXT, latitude REAL, longitude REAL, imagelink TEXT, inactivated_timestamp DATETIME, DealerSegmentId TEXT, organisationName TEXT, adTimestamp INTEGER, bodyTypeId 
                     INTEGER REFERENCES BodyType(id),
    FOREIGN KEY (fuelTypeId) REFERENCES FuelTypes (id)
);

CREATE INDEX idx_inactivecars_car_id ON inactivecars(car_id);


-- prices definition

CREATE TABLE prices (
    id INTEGER PRIMARY KEY,
    car_id TEXT,
    price REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (car_id) REFERENCES cars (car_id)
);

CREATE INDEX idx_prices_car_id ON prices(car_id);