import sqlite3


def delete_duplicate_cars(db_path):
    """
    Sletter oppføringer i cars der car_id allerede finnes i inactivecars.
    """
    # Koble til databasen
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Slett oppføringer i cars der car_id finnes i inactivecars
        cursor.execute("""
            DELETE FROM cars
            WHERE car_id IN (
                SELECT car_id FROM inactivecars
            );
        """)

        # Lagre endringene
        conn.commit()
        print("Duplikater i cars er slettet.")
    except sqlite3.Error as e:
        print(f"En feil oppstod under sletting av duplikater: {e}")
        conn.rollback()
    finally:
        # Lukk tilkoblingen
        conn.close()

# Kjør funksjonen
if __name__ == "__main__":
    db_path = "data/PrisHistorie.db"  # Oppdater med riktig databasebane
    delete_duplicate_cars(db_path)