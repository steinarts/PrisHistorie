import sqlite3
import requests
from bs4 import BeautifulSoup
import json
import base64
import time
from requests.exceptions import ConnectTimeout
from selenium import webdriver
from selenium.webdriver.common.by import By

max_attempts = 5

def insert_car_and_price(carData):
    # Connect to the database

    conn = sqlite3.connect('PrisHistorie.db')
    # Create a cursor
    c = conn.cursor()
    for car in carData:
        # Check if a car with the given VIN already exists
        c.execute("SELECT car_id FROM cars WHERE car_id = ?", (car['carId'],)) #, (car['vin'],))
        existing_car_id = c.fetchone()

        if existing_car_id is None and car['price'] != 9:
            # Insert the new car
            try:
                c.execute("""
                INSERT INTO cars (car_id, make, model, year, km, gear, fuelTypeId, vin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (car['carId'], car['make'], car['model'], car['year'], car['km'], 0, 0, 0))
            except sqlite3.IntegrityError as e:  # Antatt at du bruker sqlite3
                if 'UNIQUE constraint failed: cars.car_id' in str(e):
                    print(f"En bil med ID {car['carid']} eksisterer allerede i databasen.")
                else:
                    # Håndter andre IntegrityError-relaterte feil her om nødvendig
                    print("En annen integritetsrelatert feil oppstod:", e)

            # Insert the price for the new car
            c.execute("""
            INSERT INTO prices (car_id, price)
            VALUES (?, ?)
            """, (car['carId'], car['price']))
            
        # If the car already exists, additional logic can be added here for handling price changes
        else:
            if (car['price'] ==9):
                #delete from cars og legg i 
                c.execute("SELECT car_id FROM inactivecars WHERE car_id = ? LIMIT 1", (car['carId'],))
                carExists = c.fetchone()
                #check if we have a case of solg med pris
                if carExists is None:
                    c.execute("INSERT INTO inactivecars SELECT * FROM cars WHERE car_id = ?", (car['carId'],))
                    c.execute("DELETE FROM cars WHERE car_id = ?", (car['carId'],))

            c.execute("SELECT price FROM prices WHERE car_id = ? ORDER BY timestamp DESC LIMIT 1", (car['carId'],))
            priceFound = c.fetchone()

            if priceFound:
                price = priceFound[0]
                if (int(car['price']) != int(price)):
                # Insert the new price for the old car
                    c.execute("""
                    INSERT INTO prices (car_id, price)
                    VALUES (?, ?)
                    """, (car['carId'], car['price']))
            else:
                # Insert the price for the new car
                c.execute("""
                INSERT INTO prices (car_id, price)
                VALUES (?, ?)
                """, (car['carId'], car['price']))

                #price = None  # eller hva du vil sette som standardverdi
                #print(str((car['carId'],)) + ' Not found in prices')

    # Commit the changes
    conn.commit()

    # Close the connection
    conn.close()

def split_car_name(name):
    # Liste med toords-bilmerker
    two_word_brands = ['Land Rover', 'Alfa Romeo', 'Rolls Royce', 'Mercedes-Benz', 'Aston Martin', 'Austin Healey', 'Mitsubishi Motors', 'General Motors']
    
    # Sjekk for toords-bilmerker
    for brand in two_word_brands:
        if brand in name:
            return brand, name.replace(brand, '').strip()

    # Hvis det bare er ett ord i navnet, returner det som merket og modellen som en tom streng.
    if ' ' not in name:
        return name, ''

    # Hvis ingen toords-bilmerker finnes, deler vi navnet ved det første mellomrommet for å få merket og modellen.
    brand, model = name.split(' ', 1)
    return brand, model

def ExtractCarData(carData, car_tags):
    for tag in car_tags:
        price_div = tag.select_one('div.mb-8.flex.justify-between.whitespace-nowrap.font-bold')
        if price_div:
            km = 0
            price = 0
            year = 9
            price_spans = price_div.find_all('span')
            for span in price_spans:
                price, km, year = process_price_span(span)

        tag = tag.find('a', class_='sf-search-ad-link')
        car_id = tag.get('id')

        # Henter merke og navnet på bilen
        make,model = split_car_name(tag.text.strip())

        car_info = {
                "carId": car_id,
                "year": year,
                "price": price,
                "km": km,
                "make": make,
                "model": model
            }
        carData.append(car_info)

def process_price_span(span):
    text = span.text.strip().lower()
    price = None
    km = None
    year = None

    if text == 'solgt':
        price = 9
    elif "km" in text:
        km = text.replace("km", "").strip().replace('\xa0', '')  # Fjern "km" og strip hvite mellomrom
    elif "kr" in text:
        price = text.replace("kr", "").strip().replace('\xa0', '')
    else:
        try:
            year = int(text)  # Forsøk å konvertere til et tall (antageligvis et årstall)
        except ValueError:
            pass  # Dette var ikke et årstall
    
    return price, km, year

def main():
    # Base URL for the car page
    done = False;

    url = "https://www.finn.no/car/used/search.html"
    browser, car_brands = GetCarModels(url)

    model_inputs = browser.find_elements(By.CSS_SELECTOR, "ul.list.u-ml16 li div.input-toggle input[type='checkbox']")

    # Ekstraherer ID-verdier fra de funnede input-elementene
    model_ids = [input_elem.get_attribute('id') for input_elem in model_inputs]
    attempt=5

    browser.quit()
    for id in model_ids:
        done=False
        while done==False:    
            for pagaNo in range(100):
                url = 'https://www.finn.no/car/used/search.html?' + id.replace("-", "=") + '&sales_form=1&sort=PUBLISHED_DESC' + "&page=" + str(pagaNo+1)
                try:
                    response = requests.get(url)
                #    break
                except (ConnectTimeout, ConnectionError) as e:
                    if attempt < max_attempts - 1:  # hvis det ikke er siste forsøk
                        print(f"Koblingstidsavbrudd oppstod. Venter 60 sekunder før forsøk {attempt + 2}.")
                        time.sleep(60)
                    else:
                        print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")

                soup = BeautifulSoup(response.text, 'html.parser')
                car_tags = soup.find_all('article', {'class': ['sf-search-ad', 'sf-search-ad-legendary']})
                carData = []
                ExtractCarData(carData,car_tags)
                
                insert_car_and_price(carData)
                pagination = soup.find("a", {"class": "button button--pill button--has-icon button--icon-right"})
                if pagination == None:
                    done=True
                    break

    return carData

def GetCarModels(url):
    browser = getBrowser(url)

    # Finn bilmerker og klikk på dem for å laste inn modellene
    car_brands = getCarBrands(browser)
    for brand in car_brands:
        brand.click()
        #time.sleep(2)  # Vent litt for å sikre at innholdet er lastet

    return browser,car_brands

def getCarBrands(browser):
    car_brands = browser.find_elements(By.CSS_SELECTOR, "input[id^='make-'] + label")
    return car_brands

def getBrowser(url):
    options = webdriver.EdgeOptions()
    options.use_chromium = True  # Only for Edge version 79+
    options.headless = True
    #options.add_argument("headless")
    browser = webdriver.Edge(options=options)
    
    browser.get(url)
    return browser

if __name__ == "__main__":
    carData = main()
    print(carData)
