import sqlite3

def run_migration(db_path):
    """
    Kjør migrasjonen for å legge til  BodyType-tabellen.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Opprett bodytype-tabellen
    conn.execute('''
        CREATE TABLE IF NOT EXISTS BodyType (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            BodyType TEXT NOT NULL UNIQUE
        );
    ''')

    try:
        conn.execute('''
            ALTER TABLE cars
                      ADD COLUMN bodyTypeId 
                     INTEGER REFERENCES BodyType(id);
            
        ''')
    except sqlite3.OperationalError:
        pass  # Column already exists

    
    try:
        conn.execute('''
            ALTER TABLE inactivecars
                      ADD COLUMN bodyTypeId 
                     INTEGER REFERENCES BodyType(id);
            
        ''')
    except sqlite3.OperationalError:
        pass  # Column already exists

    # Lagre endringene
    conn.commit()
    print("Migrasjon fullført: Nye bodytype tabell lagt til.")
    conn.close()

if __name__ == "__main__":
    db_path = "data/PrisHistorie.db"  # Oppdater med riktig databasebane
    run_migration(db_path)