import sqlite3

def run_migration(db_path):
    """
    Legger til nye drivstofftyper i fuel_types-tabellen.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Legg til nye drivstofftyper
        cursor.execute("INSERT INTO FuelTypes (id, type) VALUES (?, ?)", (9, 'El'))
        cursor.execute("INSERT INTO FuelTypes (id, type) VALUES (?, ?)", (10, 'Hybrid bensin'))

        # Lagre endringene
        conn.commit()
        print("Migrasjon fullført: Nye drivstofftyper lagt til.")
    except sqlite3.Error as e:
        print(f"En feil oppstod under migrasjonen: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    db_path = "data/PrisHistorie.db"  # Oppdater med riktig databasebane
    run_migration(db_path)