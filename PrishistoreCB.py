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

#e.g. http://127.0.0.1:5001/prices/322756323
@app.route("/prices/<car_id>", methods=["GET"])
def get_prices(car_id):
    if request.method == "GET":
        price_data = get_price_data(car_id)
        return render_template("index.html", price_data=price_data)
    return render_template("index.html", price_data=None)
    
def get_price_data(car_id):
    # Koble til SQLite-databasen
    conn = sqlite3.connect("PrisHistorie.db")
    cursor = conn.cursor()

    # Hent prisdata for den angitte bil-IDen
    cursor.execute("SELECT timestamp, p.price, c.make,c.model,c.car_id FROM cars c join prices p on c.car_id=p.car_id WHERE c.car_id=?", (car_id,))
    price_data = cursor.fetchall()

    # Lukk databasetilkoblingen
    conn.close()

    return price_data

if __name__ == "__main__":
    app.run(debug=True, port = 5001)
