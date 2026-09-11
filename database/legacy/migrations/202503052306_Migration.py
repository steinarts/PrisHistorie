import sqlite3

def run_migrations():
    # Koble til databasen
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    try:
        # 1. Oppdater `inactivecars`: Sett `adtimestamp` til NULL der `timestamp = adtimestamp`
        c.execute('''
            UPDATE inactivecars
            SET adtimestamp = NULL
            WHERE timestamp = adtimestamp;
        ''')

        # 2. Oppdater `cars`: Sett `imagelink` til NULL der `imagelink = freetextmodel`
        c.execute('''
            UPDATE cars
            SET imagelink = NULL
            WHERE imagelink = freetextmodel;
        ''')

        # Lagre endringene
        conn.commit()
        print("Migrasjoner vellykket utført!")

    except sqlite3.OperationalError as e:
        print(f"Feil under migrasjon: {e}")

    finally:
        # Lukk tilkoblingen til databasen
        conn.close()

# Kjør migrasjonene
run_migrations()