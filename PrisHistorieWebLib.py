import sqlite3
from contextlib import contextmanager

import requests
from bs4 import BeautifulSoup
import time
from datetime import datetime
from requests.exceptions import ConnectTimeout
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import NoSuchElementException, TimeoutException

max_attempts = 5

@contextmanager
def db_connection():
    conn = sqlite3.connect('data/PrisHistorie.db')
    try:
        yield conn
    finally:
        conn.close()

def FindFueltypeId(drivstoff):
    fuelId = None
    
    with db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM fueltypes WHERE LOWER(type) = LOWER(?)", (drivstoff,))
        car = c.fetchone()
        
        if car is not None:
            fuelId = car[0]
        
        return fuelId

def accept_cookies(browser):
    try:
        # Finn iframe-elementet som inneholder samtykkeboksen
        iframe = WebDriverWait(browser, 5).until(
            EC.presence_of_element_located((By.XPATH, '//iframe[@title="SP Consent Message"]')))

        # Bytt til iframen
        browser.switch_to.frame(iframe)
        
        wait = WebDriverWait(browser, 5)
        godta_alle_knapp = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(),'Godta alle')]")))
        godta_alle_knapp.click()
        # Bytt tilbake til hovedinnholdet, litt usikker på om denne trengs siden cookie boksen er borte
        browser.switch_to.default_content()

    except NoSuchElementException:
        pass

def getBrowser(url):
    options = webdriver.EdgeOptions()
    options.use_chromium = True  # Only for Edge version 79+
    
    #options.add_argument("--headless")
    options.add_argument("--no-sandbox")  # Deaktiver sandbox for å unngå problemer i Docker
    options.add_argument("--disable-dev-shm-usage")  # Unngå begrensninger i /dev/shm
    options.add_argument("--verbose")

    browser = webdriver.Edge(options=options)
    #fixer ElementClickInterceptedException problemet som oppstår ved full liste
    browser.set_window_size(1920, 1280)
    #browser.maximize_window()

    browser.get(url)
    
    accept_cookies(browser)

    try:
        # Vent på at "Vis alle"-knappen skal bli tilgjengelig i DOM
        vis_alle_knapp = WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.XPATH, "//button[contains(text(),'Vis alle')]")))

    except TimeoutException:
        browser.save_screenshot("timeout_exception.png")
        raise

    # Scroll til "Vis alle"-knappen før klikk
    browser.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -200);", vis_alle_knapp)
    time.sleep(1)  # La siden oppdatere
    # Fjern reklame-bakgrunnen
    browser.execute_script("document.body.style.backgroundImage = 'none';")
    browser.execute_script("document.body.style.backgroundColor = 'transparent';")    
    vis_alle_knapp.click()

    # Vent på at bilmerkene er synlige
    # Vent spesifikt på at det første bilmerket med make=0.8093 eller lignende er lastet
    try:
        WebDriverWait(browser, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='make=0.8093']"))
        )
        print("Bilmerke-elementer er lastet.")
    except Exception as e:
        print("Feil under venting på bilmerker:", e)

    # Finn tilbake til bilmerke-seksjonen og skroll dit
    bilmerke_seksjon = browser.find_element(By.XPATH, "//h3[text()='Merke']/ancestor::button")
    browser.execute_script("arguments[0].scrollIntoView(true); window.scrollBy(0, -200);", bilmerke_seksjon)

    #scroll_to_element(browser, bilmerke_seksjon)

    return browser
