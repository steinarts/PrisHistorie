import sqlite3

def run_migrations():
    # Koble til databasen
    conn = sqlite3.connect('data/PrisHistorie.db')
    c = conn.cursor()

    try:
        c.execute('''
            UPDATE cars
            SET freetextModel = NULL
            WHERE freetextModel = 'FINN-kode';
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