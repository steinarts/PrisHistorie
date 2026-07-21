"""
API Health Check Module
Verifiserer at eksterne API-er (Finn.no, Vegvesen) har forventet struktur.
Sender varsler hvis kritiske endringer oppdages.

@author: GitHub Copilot
"""

from datetime import datetime
from typing import Dict, List, Any, Optional
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

class ApiHealthCheck:
    """
    Verifiserer API-struktur og sender varsler ved endringer.
    
    @param logFilePath: Sti til loggfil for health check-resultater (str)
    """
    
    def __init__(self, logFilePath: str = "logs/api_health_check.log"):
        self.logFilePath = logFilePath
        self.errors: List[str] = []
        self.warnings: List[str] = []
        
        # E-post konfigurasjon (kan overskrives fra miljøvariabler)
        self.emailEnabled = os.getenv('EMAIL_ALERTS_ENABLED', 'false').lower() == 'true'
        self.smtpServer = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtpPort = int(os.getenv('SMTP_PORT', '587'))
        self.senderEmail = os.getenv('SENDER_EMAIL', '')
        self.senderPassword = os.getenv('SENDER_PASSWORD', '')
        self.recipientEmail = os.getenv('RECIPIENT_EMAIL', '')
        
    def checkFinnApiStructure(self, apiResponse: Dict[str, Any]) -> bool:
        """
        Verifiserer at Finn.no API har forventet struktur.
        
        @param apiResponse: JSON-respons fra Finn.no API (dict)
        @return: True hvis strukturen er OK, False hvis kritiske feil (bool)
        @throws: None
        """
        isHealthy = True
        
        # Sjekk at 'filters' finnes
        if 'filters' not in apiResponse:
            self._addError("KRITISK: 'filters' mangler i Finn.no API-respons")
            return False
        
        filters = apiResponse.get('filters', [])
        filterNames = [f.get('name') for f in filters]
        
        # Sjekk kritiske filtre
        requiredFilters = ['variant', 'price', 'year', 'mileage']
        missingFilters = [f for f in requiredFilters if f not in filterNames]
        
        if missingFilters:
            self._addError(f"KRITISK: Manglende filtre: {', '.join(missingFilters)}")
            isHealthy = False
        
        # Sjekk at 'variant' har forventet struktur
        variantFilter = next((f for f in filters if f.get('name') == 'variant'), None)
        if variantFilter:
            filterItems = variantFilter.get('filter_items', [])
            if not filterItems:
                self._addWarning("ADVARSEL: 'variant' filter er tomt")
            else:
                # Sjekk første item har forventet struktur
                firstItem = filterItems[0]
                expectedKeys = ['display_name', 'value', 'filter_items']
                missingKeys = [k for k in expectedKeys if k not in firstItem]
                if missingKeys:
                    self._addWarning(f"ADVARSEL: Manglende nøkler i variant: {', '.join(missingKeys)}")
        
        # Sjekk andre viktige filtre
        expectedFilters = {
            'price': ['filter_items'],
            'year': ['filter_items'],
            'mileage': ['filter_items']
        }
        
        for filterName, requiredKeys in expectedFilters.items():
            filterObj = next((f for f in filters if f.get('name') == filterName), None)
            if filterObj:
                for key in requiredKeys:
                    if key not in filterObj:
                        self._addWarning(f"ADVARSEL: '{filterName}' mangler '{key}'")
        
        return isHealthy
    
    def checkFinnAdStructure(self, ad: Dict[str, Any]) -> bool:
        """
        Verifiserer at en Finn.no annonse har forventet struktur.
        
        @param ad: Annonse-objekt fra Finn.no (dict)
        @return: True hvis strukturen er OK (bool)
        """
        requiredFields = ['id', 'heading', 'location', 'price', 'image']
        missingFields = []
        
        for field in requiredFields:
            if field == 'price':
                # Spesialhåndtering for price (nested struktur)
                if not ad.get('price', {}).get('total', {}).get('amount'):
                    missingFields.append(field)
            else:
                # Vanlige felter
                if field not in ad or not ad[field]:
                    missingFields.append(field)
        
        if missingFields:
            self._addWarning(f"ADVARSEL: Annonse mangler felter: {', '.join(missingFields)} (ID: {ad.get('id', 'unknown')})")
            return False
        
        return True
    
    def checkVegvesenApiResponse(self, response: Dict[str, Any], endpoint: str) -> bool:
        """
        Verifiserer at Vegvesen API har forventet struktur.
        
        @param response: JSON-respons fra Vegvesen API (dict)
        @param endpoint: Hvilken endpoint som ble kalt (str)
        @return: True hvis strukturen er OK (bool)
        """
        if endpoint == "kjoretoydata":
            if 'kjoretoydataListe' not in response:
                self._addError(f"KRITISK: Vegvesen API mangler 'kjoretoydataListe'")
                return False
        
        return True
    
    def _addError(self, message: str):
        """Legger til en feilmelding."""
        self.errors.append(f"[{self._getTimestamp()}] {message}")
        print(f"❌ {message}")
    
    def _addWarning(self, message: str):
        """Legger til en advarsel."""
        self.warnings.append(f"[{self._getTimestamp()}] {message}")
        print(f"⚠️ {message}")
    
    def _getTimestamp(self) -> str:
        """Returnerer timestamp for logging."""
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def logResults(self):
        """
        Skriver health check-resultater til loggfil.
        
        @return: None
        @throws: IOError ved feil i filskriving
        """
        import os
        
        # Opprett logs-mappe hvis den ikke finnes
        logDir = os.path.dirname(self.logFilePath)
        if logDir and not os.path.exists(logDir):
            os.makedirs(logDir)
        
        with open(self.logFilePath, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"Health Check: {self._getTimestamp()}\n")
            f.write(f"{'='*60}\n")
            
            if self.errors:
                f.write("\n🔴 FEIL:\n")
                for error in self.errors:
                    f.write(f"  {error}\n")
            
            if self.warnings:
                f.write("\n⚠️ ADVARSLER:\n")
                for warning in self.warnings:
                    f.write(f"  {warning}\n")
            
            if not self.errors and not self.warnings:
                f.write("\n✅ Ingen problemer oppdaget\n")
    
    def hasErrors(self) -> bool:
        """Returnerer True hvis det er kritiske feil."""
        return len(self.errors) > 0
    
    def hasWarnings(self) -> bool:
        """Returnerer True hvis det er advarsler."""
        return len(self.warnings) > 0
    
    def getReport(self) -> str:
        """
        Returnerer en tekstrapport av health check.
        
        @return: Formatert rapport (str)
        """
        report = f"\n{'='*60}\n"
        report += f"API Health Check - {self._getTimestamp()}\n"
        report += f"{'='*60}\n"
        
        if self.errors:
            report += f"\n🔴 FEIL ({len(self.errors)}):\n"
            for error in self.errors:
                report += f"  {error}\n"
        
        if self.warnings:
            report += f"\n⚠️ ADVARSLER ({len(self.warnings)}):\n"
            for warning in self.warnings:
                report += f"  {warning}\n"
        
        if not self.errors and not self.warnings:
            report += "\n✅ Alle API-er har forventet struktur\n"
        
        report += f"{'='*60}\n"
        return report
    
    def sendEmailAlert(self, subject: str = "🚨 PrisHistorie API Alert"):
        """
        Sender e-postvarsel om API-endringer.
        
        @param subject: E-post emne (str)
        @return: True hvis e-post ble sendt, False ellers (bool)
        @throws: None (fanger exceptions internt)
        """
        if not self.emailEnabled:
            print("📧 E-postvarsling er deaktivert (sett EMAIL_ALERTS_ENABLED=true)")
            return False
        
        if not all([self.senderEmail, self.senderPassword, self.recipientEmail]):
            print("⚠️ E-post konfigurasjon mangler. Sjekk miljøvariabler.")
            return False
        
        try:
            # Opprett e-post melding
            msg = MIMEMultipart()
            msg['From'] = self.senderEmail
            msg['To'] = self.recipientEmail
            msg['Subject'] = subject
            
            # E-post body (bruk rapporten)
            body = self.getReport()
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # Send via SMTP
            with smtplib.SMTP(self.smtpServer, self.smtpPort) as server:
                server.starttls()  # Sikker forbindelse
                server.login(self.senderEmail, self.senderPassword)
                server.send_message(msg)
            
            print(f"✅ E-postvarsel sendt til {self.recipientEmail}")
            return True
            
        except Exception as e:
            print(f"❌ Kunne ikke sende e-post: {e}")
            return False
