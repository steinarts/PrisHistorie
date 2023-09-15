from flask import Flask, render_template, request
import sqlite3

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        car_id = request.form["car_id"]
        price_data = get_price_data(car_id)
        return render_template("index.html", price_data=price_data)
    return render_template("index.html", price_data=None)

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
    app.run(debug=True)
