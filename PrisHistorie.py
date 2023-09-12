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
        c.execute("SELECT car_id FROM cars WHERE car_id = ?", (car['id'],)) #, (car['vin'],))
        existing_car_id = c.fetchone()

        if existing_car_id is None:
            # Find the fuelTypeId for the given fuel type
            drivstoff = car['additional_data'].get('Drivstoff')
            if drivstoff:
                if drivstoff == 'El + Bensin' or drivstoff == 'El + Diesel':
                    drivstoff = 'Hybrid'
                c.execute("SELECT id FROM FuelTypes WHERE type = ?", (drivstoff,))
                fuel_type_id = c.fetchone()[0]
            else:
                fuel_type_id = ""
                
            # Insert the new car
            try:
                c.execute("""
                INSERT INTO cars (car_id, make, model, year, km, gear, fuelTypeId, vin)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (car['id'], car['make'], car['model'], car['additional_data'].get('Modellår'), car['additional_data'].get('Kilometer'), car['additional_data'].get('Girkasse'), fuel_type_id, car['vin']))
            except sqlite3.IntegrityError as e:  # Antatt at du bruker sqlite3
                if 'UNIQUE constraint failed: cars.car_id' in str(e):
                    print(f"En bil med ID {car['id']} eksisterer allerede i databasen.")
                else:
                    # Håndter andre IntegrityError-relaterte feil her om nødvendig
                    print("En annen integritetsrelatert feil oppstod:", e)

            # Insert the price for the new car
            c.execute("""
            INSERT INTO prices (car_id, price)
            VALUES (?, ?)
            """, (car['id'], car['price']))
            
        # If the car already exists, additional logic can be added here for handling price changes
        else:
            c.execute("SELECT price FROM prices WHERE car_id = ?", (car['id'],))
            priceFound = c.fetchone()

            if priceFound:
                price = priceFound[0]
                if (car['price'] != int(price)):
                # Insert the new price for the old car
                    c.execute("""
                    INSERT INTO prices (car_id, price)
                    VALUES (?, ?)
                    """, (car['id'], car['price']))
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

    browser.quit()
    for id in model_ids:
        done=False
        while done==False:    
            for pagaNo in range(100):

                url = 'https://www.finn.no/car/used/search.html?' + id.replace("-", "=") + '&sales_form=1&sort=PUBLISHED_DESC' + "&page=" + str(pagaNo+1)

                response = requests.get(url)

                soup = BeautifulSoup(response.text, 'html.parser')
                car_tags = soup.find_all('article', {'class': ['sf-search-ad', 'sf-search-ad-legendary']})
                carData = []
                #ExtractCarData(carData,car_tags)
                
                car_ids = []
                for tag in car_tags:
                    car_id_div = tag.find('div', {'class': 'absolute'})
                    if car_id_div:
                        car_id = car_id_div.get('aria-owns').replace('search-ad-', '')
                        car_ids.append(car_id)

                
                for car_id in car_ids:
                    car_url = f'https://www.finn.no/car/used/ad.html?finnkode={car_id}'
                    for attempt in range(max_attempts):
                        try:
                            car_page = requests.get(car_url)
                            break
                        except ConnectTimeout:
                            if attempt < max_attempts - 1:  # hvis det ikke er siste forsøk
                                print(f"Koblingstidsavbrudd oppstod. Venter 60 sekunder før forsøk {attempt + 2}.")
                                time.sleep(60)
                            else:
                                print(f"Koblingstidsavbrudd oppstod etter {max_attempts} forsøk. Avslutter.")
                    
                    car_soup = BeautifulSoup(car_page.text, 'html.parser')

                    # Find the car make and model
                    car_info_divs = car_soup.find_all('div', {'class': 'panel'})
                    try:
                        car_info_div = car_info_divs[2]
                    except IndexError:
                        print("Elementet på indeks 2 eksisterer ikke i listen! carId " + car_id)
                        continue
                    
                    car_make_temp = car_info_div.find('h1', {'class': 'u-t2 u-word-break'})
                    #car_model = car_info_div.find('p')
                    #if car_model:
                    #    car_model = car_model.text.strip()
                    
                    if car_make_temp:
                        car_make_temp = car_make_temp.text.strip()
                        car_make,car_model = split_car_name(car_make_temp)

                    #car_make = car_info_div.find('h1', {'class': 'u-t2 u-word-break'}).text.strip()
                    #car_model = car_info_div.find('p').text.strip()

                    # finn prisen fra totalpris
                    element = car_soup.find('tjm-ad-entry')
                    if element: # bare for private?
                        decodedStr = element['data-config']
                        decodedBytes = base64.b64decode(decodedStr)
                        jsonStr = decodedBytes.decode('utf-8')
                        data = json.loads(jsonStr)
                        totalPris = data['model']['totalPrice']
                    else:
                        priceTag = car_soup.find('span', {'class': 'u-t3'})
                        totalPris = priceTag.text.replace('\xa0', '').replace(' kr', '')

                    # Find the VIN
                    all_car_info_divs = car_soup.find('dl', {'class': 'list-descriptive'})
                    #price_tag = all_car_info_divs.find('dt', text='Pris eks omreg').find_next_sibling('dd')        
                    if all_car_info_divs.find('dt', text='Chassis nr. (VIN)'):
                        vin_div = all_car_info_divs.find('dt', text='Chassis nr. (VIN)').find_next_sibling('dd')
                    else:
                        reg_nr_element = all_car_info_divs.find('dt', text='Reg.nr.')
                        if reg_nr_element:
                            vin_div = reg_nr_element.find_next_sibling('dd')
                        else:
                            vin_div = None
                        #vin_div = all_car_info_divs.find('dt', text='Reg.nr.').find_next_sibling('dd')
                    
                    #if price_tag:
                    #    price_tag = price_tag.text.replace('\xa0', '').replace('kr', '').strip()
                    if vin_div:
                        vin_div = vin_div.text.strip()
                        
                    # Find the car details
                    detail_divs = car_soup.find_all('div', {'class': 'grid grid--cols2to4 t-grid'})
                    details = {}
                    for div in detail_divs:
                        media_bodies = div.find_all('div', class_='media__body')
                        for body in media_bodies:
                            key_value = body.get_text().strip().split('\n')
                            key = key_value[0].strip()
                            value = key_value[1].strip() if len(key_value) > 1 else None
                            details[key] = value

                    
                    #kilometer = details['Kilometer'].replace('\xa0', '').split(' ')[0]
                    kilometer_value = details.get('Kilometer')
                    if kilometer_value:
                        kilometer = kilometer_value.replace('\xa0', '').split(' ')[0]
                    else:
                        print("Nøkkelen 'Kilometer' finnes ikke i ordboken.")
                        kilometer = 0  # eller en annen standardverdi du vil bruke
                    
                    details['Kilometer'] = int(kilometer)
                
                    if totalPris and vin_div:
                        #price = price_tag.text.replace('\xa0kr', '').replace('\xa0', '')
                        carData.append([car_make, car_model, int(totalPris), vin_div.strip(),details, car_id])
                    
                    vin_div = None
                    
                keys = ["make", "model", "price", "vin", "additional_data", "id"]

                # Konverterer listen av lister til en liste av ordbøker
                carData_dict = [dict(zip(keys, car)) for car in carData]

                # Skriver ut de første to ordbøkene for å sjekke resultatet
                #print(carData_dict[:2])        
                insert_car_and_price(carData_dict)
                pagination = soup.find("a", {"class": "button button--pill button--has-icon button--icon-right"})
                if pagination == None:
                    done=True
                    break

    return carData

if __name__ == "__main__":
    carData = main()
    print(carData)
