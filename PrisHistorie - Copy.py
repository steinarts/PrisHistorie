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

        if existing_car_id is None:
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
            c.execute("SELECT price FROM prices WHERE car_id = ?", (car['carId'],))
            priceFound = c.fetchone()

            if priceFound:
                price = priceFound[0]
                if (car['price'] != int(price)):
                # Insert the new price for the old car
                    c.execute("""
                    INSERT INTO prices (car_id, price)
                    VALUES (?, ?)
                    """, (car['carId'], car['price']))
            else:
                price = None  # eller hva du vil sette som standardverdi
                print(str((car['id'],)) + ' Not found in prices')


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
            # Hvis merket finnes i navnet, deler vi navnet ved merket og returnerer merket og modellen som to separate strenger.
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
            price_spans = price_div.find_all('span')
            if price_spans and len(price_spans) >= 3:  # Verify that we have at least 3 span elements
                year = price_spans[0].text
                km = price_spans[1].text.replace(' km','').replace('\xa0', '')
                price_text = price_spans[2].text.replace(' kr', '').replace('\xa0', '')
                if price_text.isdigit():  # Verify that the price_text can be converted to an integer
                    price = int(price_text)

        tag = tag.find('a', class_='sf-search-ad-link')
        # Henter ID
        car_id = tag.get('id')

        # Henter navnet på bilen
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

def main():
    # Base URL for the car page
    done = False;

    car_list = []

    url = "https://www.finn.no/car/used/search.html"

    options = webdriver.EdgeOptions()
    options.use_chromium = True  # Only for Edge version 79+
    options.headless = True
    browser = webdriver.Edge(options=options)
    
    browser.get(url)


    # Finn bilmerker og klikk på dem for å laste inn modellene
    car_brands = browser.find_elements(By.CSS_SELECTOR, "input[id^='make-'] + label")
    #car_brands = browser.find_elements_by_css_selector("ul.list li div.input-toggle label")

    for brand in car_brands:
        brand.click()
        #time.sleep(2)  # Vent litt for å sikre at innholdet er lastet

    # Nå, bruk BeautifulSoup for å analysere innholdet
    soup = BeautifulSoup(browser.page_source, 'html.parser')
    
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

                #try:
                response = requests.get(url)
                #    break
                #except ConnectTimeout:
                #    if attempt < max_attempts - 1:  # hvis det ikke er siste forsøk
                #        print(f"Koblingstidsavbrudd oppstod. Venter 60 sekunder før forsøk {attempt + 2}.")
                #        time.sleep(60)
                #    else:
                #        print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")

                soup = BeautifulSoup(response.text, 'html.parser')
                car_tags = soup.find_all('article', {'class': ['sf-search-ad', 'sf-search-ad-legendary']})
                carData = []
                ExtractCarData(carData,car_tags)
                

                # Konverterer listen av lister til en liste av ordbøker
                #carData_dict = [dict(zip(keys, car)) for car in carData]

                # Skriver ut de første to ordbøkene for å sjekke resultatet
                #print(carData_dict[:2])        
                insert_car_and_price(carData)
                pagination = soup.find("a", {"class": "button button--pill button--has-icon button--icon-right"})
                if pagination == None:
                    done=True
                    break

    return carData

if __name__ == "__main__":
    carData = main()
    print(carData)
