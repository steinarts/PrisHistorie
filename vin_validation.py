import asyncio
import re

# -------------------------------
#   MODERNE VIN (17 tegn)
# -------------------------------

VIN_TRANSLITERATION = {
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5, "P": 7, "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
    "0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
    "7": 7, "8": 8, "9": 9
}

VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def is_valid_modern_vin(vin: str) -> bool:
    """
    Validerer moderne 17-tegns VIN.
    - Sjekker tegnsett for alle.
    - Sjekker kontrollsiffer KUN for nordamerikanske VIN (1,2,3,4,5).
    """
    vin = vin.upper()

    # Tillatte tegn (uten I, O, Q)
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        return False

    # Bare VIN som starter med 1–5 (USA/Canada/Mexico) har garantert gyldig check digit
    if vin[0] in "12345":
        total = 0
        for char, weight in zip(vin, VIN_WEIGHTS):
            total += VIN_TRANSLITERATION[char] * weight

        remainder = total % 11
        expected_check_digit = "X" if remainder == 10 else str(remainder)

        if vin[8] != expected_check_digit:
            return False

    # For resten (f.eks. WDB... i Europa) er vi fornøyd med tegnsett + lengde
    return True


# -------------------------------
#   GAMMEL VIN (<1981)
# -------------------------------

def is_valid_old_vin(vin: str) -> bool:
    """
    Validerer pre-1981 VIN.
    Disse hadde ingen global standard og manglet kontrollsiffer.
    Vanlig lengde var 11–13 tegn.
    """
    vin = vin.upper()

    if len(vin) not in (11, 12, 13):
        return False

    # Tillatte tegn, samme som moderne VIN, men uten lengdekravet
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{11,13}", vin):
        return False

    return True


# -------------------------------
#   KOMBINERT FUNKSJON
# -------------------------------

def normalize_vin(vin: str) -> str:
    """
    Normaliserer VIN:
    - trim whitespace
    - gjør til uppercase
    - fjerner trailing 0 og X (typisk padding fra gamle VIN i moderne felter)
    """
    vin = vin.strip().upper()
    # Fjern alle 0 og X på slutten (padding)
    vin = re.sub(r"[0X]+$", "", vin)
    return vin


def is_valid_vin(vin: str) -> bool:
    """
    Validerer både moderne VIN (17 tegn med kontrollsiffer)
    og gamle VIN (<1981 med 11–13 tegn).
    """
    #vin = normalize_vin(vin)
    vin = vin.strip().upper()

    if len(vin) == 17:
        return is_valid_modern_vin(vin)
    elif len(vin) in (11, 12, 13):
        return is_valid_old_vin(vin)
    else:
        return False


if __name__ == "__main__":
    async def main():
        parameter = "understellsnummer"  # eller "kjennemerke"
        verdi = "WDB2112061A890157"  # eller "LY11129" JZA800022606xxxxxx
     
        # Hent data
        resultat = is_valid_vin(verdi)
        print(resultat)

    asyncio.run(main())

