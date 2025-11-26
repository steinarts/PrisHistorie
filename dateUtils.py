from datetime import datetime, timezone
import re

def convert_date_format_fra_annonse(date_string):
    """
    Converts a Norwegian date string (e.g., '18. juli 2024, 08:25')
    to a standard format (e.g., '2024-07-18 08:25:00').
    """
    try:
        return convert_norwegian_date_to_standard(date_string)
    except ValueError as e:
        print(f"❌ Error parsing date '{date_string}': {e}")
        return None

def convert_norwegian_date_to_standard(date_string):
    """
    Konverterer en norsk dato (f.eks. '6. juli 2024, 07:26') til standardformat (f.eks. '2024-07-06 07:26:00').
    """
    # Norsk måned til engelsk måned mapping
    norwegian_to_english_months = {
        "januar": "January",
        "februar": "February",
        "mars": "March",
        "april": "April",
        "mai": "May",
        "juni": "June",
        "juli": "July",
        "august": "August",
        "september": "September",
        "oktober": "October",
        "november": "November",
        "desember": "December"
    }

    # Ekstraher dato og tid
    match = re.match(r"(\d{1,2})\.\s(\w+)\s(\d{4}),\s(\d{2}:\d{2})", date_string)
    if not match:
        raise ValueError(f"Datoformatet stemmer ikke: {date_string}")

    day, norwegian_month, year, time = match.groups()
    english_month = norwegian_to_english_months.get(norwegian_month.lower())

    if not english_month:
        raise ValueError(f"Ukjent måned: {norwegian_month}")

    # Konstruer standardformat
    standard_date_string = f"{year}-{english_month[:3]}-{int(day):02d} {time}:00"
    return datetime.strptime(standard_date_string, "%Y-%b-%d %H:%M:%S")

def convert_iso_to_standard_format(iso_timestamp):
    """
    Converts an ISO 8601 timestamp (e.g., 2024-08-08T17:38:51.274+02:00)
    to a standard format (e.g., 2024-07-05 19:54:52).
    Handles empty or invalid input gracefully.
    """
    if not iso_timestamp:
        return None
    try:
        if "." in iso_timestamp:
            date_part, time_part = iso_timestamp.split("T")
            time_part, offset = time_part.split("+") if "+" in time_part else time_part.split("-")
            if "." in time_part:
                seconds, fraction = time_part.split(".")
                fraction = fraction.ljust(3, "0")[:3]
                time_part = f"{seconds}.{fraction}"
            iso_timestamp = f"{date_part}T{time_part}+{offset}" if "+" in iso_timestamp else f"{date_part}T{time_part}-{offset}"
        dt = datetime.fromisoformat(iso_timestamp).astimezone(timezone.utc)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except ValueError as e:
        print(f"❌ Invalid ISO timestamp '{iso_timestamp}': {e}")
        return None
