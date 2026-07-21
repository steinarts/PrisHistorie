import asyncio
from datetime import datetime, timezone
import os
from dotenv import load_dotenv, find_dotenv
import aiohttp

# Last inn miljøvariabler fra .env-filen
dotenv_path = find_dotenv(usecwd=True)
if dotenv_path:
    load_dotenv(dotenv_path)
else:
    # Fallback til standard oppslag hvis prosjektet kjøres fra annen mappe.
    load_dotenv()

# Global semaphore for Vegvesen API
vegvesenSemaphore = asyncio.Semaphore(3)  # Max 3 concurrent requests

async def hent_kjoretoydata(parameter, verdi):
    """
    Fetches vehicle data from an API using the given parameter and value.
    Stops immediately on rate-limiting (429 Too Many Requests) errors.
    """
    
    url = "https://akfell-datautlevering.atlas.vegvesen.no/enkeltoppslag/kjoretoydata"
    api_key = (
        os.getenv("KJORETOY_API_KEY")
        or os.getenv("VEGVESEN_API_KEY")
        or os.getenv("SVV_API_KEY")
    )

    if not api_key:
        print(
            "API-nøkkel mangler i miljøvariabler. "
            "Sett KJORETOY_API_KEY (evt. VEGVESEN_API_KEY/SVV_API_KEY) i .env."
        )
        return {"feil": "API-nøkkel mangler"}

    headers = {"SVV-Authorization": api_key}
    params = {parameter: verdi}

    try:
        async with aiohttp.ClientSession() as session:
            async with vegvesenSemaphore:  # ✅ Rate limit ALL calls!
                async with session.get(url, headers=headers, params=params, timeout=5) as response:
                    if response.status == 429:
                        retryAfterHeader = response.headers.get('Retry-After', '3600')
                        retryAfterSeconds = parse_retry_after(retryAfterHeader)
                        
                        print(f"❌ HTTP error 429 for URL {url}: Too Many Requests")
                        print(f"⏰ Rate limit resets in {retryAfterSeconds} seconds ({retryAfterSeconds/3600:.1f} hours)")
                        
                        if is_iso_timestamp(retryAfterHeader):
                            print(f"📅 Rate limit resets at: {retryAfterHeader}")
                        
                        return {
                            "feil": "HTTP error 429",
                            "retry_after": retryAfterSeconds  # ✅ Always returns seconds!
                        }
                    
                    # ✅ Handle other HTTP errors
                    if response.status != 200:
                        print(f"❌ HTTP error {response.status} for URL {url}: {response.reason}")
                        return {
                            "feil": f"HTTP error {response.status}",
                            "message": response.reason
                        }
                    
                    # ✅ Handle successful response
                    contentType = response.headers.get('Content-Type', '')
                    if 'application/json' not in contentType:
                        print(f"❌ HTTP error 0 for URL {url}: Attempt to decode JSON with unexpected mimetype: {contentType}")
                        return {
                            "feil": "Invalid content type",
                            "content_type": contentType
                        }
                    
                    data = await response.json()
                    return data
                
    except asyncio.TimeoutError:
        print(f"❌ Timeout error for URL {url}")
        return {"feil": "Timeout"}
    
    except aiohttp.ClientError as e:
        print(f"❌ Request error for URL {url}: {e}")
        return {"feil": "Request failed"}
    
    except Exception as e:
        print(f"❌ Unexpected error for URL {url}: {e}")
        return {"feil": "Unknown error"}


def parse_retry_after(retryAfter):
    """
    Parses Retry-After header supporting both formats:
    - Delay-seconds: "3600" → 3600 seconds
    - ISO 8601 timestamp: "2025-12-07T00:00+01:00" → seconds until that time
    
    @param retryAfter: Value from Retry-After HTTP header (str)
    @return: Seconds to wait before retrying (int)
    @throws: None - returns default 3600 on parse failure
    @author: GitHub Copilot
    """
    # ✅ Try parsing as integer (delay-seconds format)
    try:
        return int(retryAfter)
    except (ValueError, TypeError):
        pass
    
    # ✅ Try parsing as ISO 8601 timestamp
    try:
        # Parse ISO 8601 with timezone offset
        # Example: "2025-12-07T00:00+01:00" → datetime object
        retryTime = datetime.fromisoformat(retryAfter)
        
        # Get current time in UTC (API timestamp is Oslo time = UTC+1)
        nowTime = datetime.now(datetime.timezone.utc)
        
        # Ensure retryTime is timezone-aware for comparison
        if retryTime.tzinfo is None:
            retryTime = retryTime.replace(tzinfo=timezone.utc)
        
        # Calculate seconds until retry time
        deltaSeconds = int((retryTime - nowTime).total_seconds())
        
        # ✅ Never return negative (if timestamp is in past, retry now)
        return max(deltaSeconds, 0)
        
    except (ValueError, AttributeError, TypeError) as e:
        print(f"⚠️ Failed to parse Retry-After header '{retryAfter}': {e}")
        return 3600  # ✅ Fallback: default 1 hour


def is_iso_timestamp(value):
    """
    Checks if a string is an ISO 8601 timestamp.
    
    @param value: String to check (str)
    @return: True if ISO timestamp, False otherwise (bool)
    @throws: None
    @author: GitHub Copilot
    """
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False
    
# Eksempel på bruk
if __name__ == "__main__":
    """"
    async def main():
        parameter = "understellsnummer"  # eller "kjennemerke"
        verdi = "SCBDF33S7SC019101"  # SCFSMGFW9SGN08948 eller "LY11129"
     
        # Hent data
        resultat = await hent_kjoretoydata(parameter, verdi)
        if "understellsnummer" in resultat:
            print(resultat['understellsnummer'])
        print(resultat)

    asyncio.run(main())
    """
# ... existing imports ...

if __name__ == "__main__":
    async def main():
        """
        Test hent_kjoretoydata with specific VIN to verify API response structure.
        
        @return: None
        @throws: None - all exceptions caught and logged
        @author: GitHub Copilot
        """
        import json
        
        # ✅ TEST 1: VIN lookup (understellsnummer → kjennemerke)
        print("\n" + "="*60)
        print("🧪 TEST 1: VIN LOOKUP")
        print("   VIN: SCBDF33S7SC019101")
        print("   Parameter: understellsnummer")
        print("   Expected: Should return kjennemerke (RegNo)")
        print("="*60 + "\n")
        
        parameter = "understellsnummer"
        verdi = "SCBDF33S7SC019101"
        
        resultat = await hent_kjoretoydata(parameter, verdi)
        
        print("\n📥 RAW API RESPONSE:")
        print(f"   Type: {type(resultat)}")
        print(f"   Content:")
        print(json.dumps(resultat, indent=2, ensure_ascii=False))
        
        # ✅ TEST 2: Check if response matches expected format
        print("\n" + "="*60)
        print("🔍 RESPONSE ANALYSIS:")
        
        if isinstance(resultat, dict):
            if "feil" in resultat:
                print(f"   ❌ Error response: {resultat.get('feil')}")
                if "message" in resultat:
                    print(f"      Message: {resultat.get('message')}")
            
            elif "kjoretoydataListe" in resultat:
                print(f"   ✅ Success response with kjoretoydataListe")
                
                kjoretoydataListe = resultat.get("kjoretoydataListe")
                print(f"   Number of vehicles: {len(kjoretoydataListe)}")
                
                if kjoretoydataListe:
                    kjoretoy = kjoretoydataListe[0]
                    print(f"   Keys in vehicle object: {list(kjoretoy.keys())}")
                    
                    # Check Location 1: kjoretoyId dict
                    if "kjoretoyId" in kjoretoy:
                        print(f"\n   📍 Location 1 (kjoretoyId dict):")
                        kjoretoyId = kjoretoy.get("kjoretoyId")
                        print(f"      Keys: {list(kjoretoyId.keys())}")
                        print(f"      kjennemerke: {kjoretoyId.get('kjennemerke')}")
                        print(f"      understellsnummer: {kjoretoyId.get('understellsnummer')}")
                    
                    # Check Location 2: top-level
                    if "kjennemerke" in kjoretoy:
                        print(f"\n   📍 Location 2 (top-level):")
                        kjennemerke = kjoretoy.get("kjennemerke")
                        print(f"      Type: {type(kjennemerke)}")
                        print(f"      Value: {kjennemerke}")
                    
                    # Check for registrertForstegangPaEierskap
                    if "registrering" in kjoretoy:
                        registrering = kjoretoy.get("registrering")
                        print(f"\n   📅 Registration info:")
                        print(f"      Keys: {list(registrering.keys()) if isinstance(registrering, dict) else 'N/A'}")
                        if isinstance(registrering, dict):
                            print(f"      registrertForstegangPaEierskap: {registrering.get('registrertForstegangPaEierskap')}")
        
        else:
            print(f"   ⚠️ Unexpected response type: {type(resultat)}")
        
        print("="*60 + "\n")
    
    # ✅ Run the test
    asyncio.run(main())    