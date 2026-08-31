"""
Migrate PrisHistorie data from SQLite to PostgreSQL.

Prerequisites:
    1. Create the PostgreSQL schema first with database/postgresql-schema.sql
    2. Install Psycopg 3:
         pip install "psycopg[binary]"
    3. Set PG_DSN, for example:
         $env:PG_DSN="postgresql://prishistorie:password@localhost:5432/prishistorie"
    4. Run:
         python database/migrate_sqlite_to_postgres.py

The migration:
    - preserves FuelTypes, DealerSegment and BodyType IDs
    - merges SQLite cars + inactivecars into PostgreSQL cars
    - maps active SQLite cars to ad_status='active'
    - maps inactivecars to ad_status='inactive'
    - maps inactivecars.inactivated_timestamp to ad_status_changed_at
    - preserves adTimestamp as BIGINT milliseconds
    - migrates prices by car_id
    - migrates status_check_progress
    - does NOT migrate the legacy demo table

The script expects an empty PostgreSQL target database.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg


DEFAULT_SQLITE_DB = Path("data/PrisHistorie.db")
LOCAL_TIMEZONE = ZoneInfo("Europe/Oslo")


def sqlite_datetime(value):
    """Convert a SQLite local datetime value to timezone-aware Python datetime."""
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None

        # Current PrisHistorie values look like: 2026-08-28 10:09:09.
        # fromisoformat also accepts fractional seconds when present.
        dt = datetime.fromisoformat(text)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=LOCAL_TIMEZONE)

    return dt


def as_int(value, field_name: str, *, nullable: bool = True):
    """Safely convert SQLite TEXT/INTEGER values to PostgreSQL integer values."""
    if value is None or value == "":
        if nullable:
            return None
        raise ValueError(f"{field_name} cannot be NULL")

    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Could not convert {field_name} value {value!r} to integer"
        ) from exc


def normalize_fuel_type_id(value):
    if value is None or value == "" or value == 0 or value == "0":
        return None

    return int(value)

def get_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]


def ensure_target_is_empty(pg: psycopg.Connection) -> None:
    """Abort instead of accidentally duplicating a previous migration."""
    tables = (
        "cars",
        "prices",
        "fuel_types",
        "dealer_segment",
        "body_type",
    )

    with pg.cursor() as cur:
        non_empty = {}
        for table in tables:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            count = cur.fetchone()[0]
            if count:
                non_empty[table] = count

    if non_empty:
        details = ", ".join(f"{table}={count}" for table, count in non_empty.items())
        raise RuntimeError(
            "PostgreSQL target is not empty. "
            f"Refusing to migrate into it: {details}"
        )


def validate_source(sqlite: sqlite3.Connection) -> None:
    """Run checks that would otherwise fail later because PostgreSQL enforces integrity."""
    required_tables = {
        "cars",
        "inactivecars",
        "prices",
        "FuelTypes",
        "DealerSegment",
        "BodyType",
        "status_check_progress",
    }

    existing = {
        row[0]
        for row in sqlite.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }

    missing = required_tables - existing
    if missing:
        raise RuntimeError(
            "SQLite database is missing required tables: "
            + ", ".join(sorted(missing))
        )

    # Overlap between cars and inactivecars is allowed. The cars row wins.
    # Orphan price car_id values are also allowed; placeholder cars rows are
    # created for them later so the PostgreSQL foreign key can be satisfied.

    # All non-zero fuel type IDs must exist in the lookup table. ID 0 is a
    # legacy "unknown" value and is intentionally migrated as NULL.
    missing_fuel_ids = sqlite.execute(
        """
        SELECT fuelTypeId
        FROM (
            SELECT fuelTypeId FROM cars
            UNION
            SELECT fuelTypeId FROM inactivecars
        ) x
        WHERE fuelTypeId IS NOT NULL
        AND TRIM(CAST(fuelTypeId AS TEXT)) <> ''
        AND CAST(fuelTypeId AS INTEGER) <> 0
        AND NOT EXISTS (
            SELECT 1
            FROM FuelTypes f
            WHERE f.id = CAST(x.fuelTypeId AS INTEGER)
        )
        ORDER BY CAST(fuelTypeId AS INTEGER)
        """
    ).fetchall()

    if missing_fuel_ids:
        ids = ", ".join(str(row[0]) for row in missing_fuel_ids)
        raise RuntimeError(
            "Source contains fuelTypeId values missing from FuelTypes: " + ids
        )


def migrate_lookup_tables(sqlite: sqlite3.Connection, pg: psycopg.Connection) -> None:
    with pg.cursor() as cur:
        rows = sqlite.execute(
            "SELECT id, type FROM FuelTypes ORDER BY id"
        ).fetchall()
        cur.executemany(
            "INSERT INTO fuel_types (id, type) VALUES (%s, %s)",
            rows,
        )

        rows = sqlite.execute(
            "SELECT id, name FROM DealerSegment ORDER BY id"
        ).fetchall()
        cur.executemany(
            "INSERT INTO dealer_segment (id, name) VALUES (%s, %s)",
            rows,
        )

        rows = sqlite.execute(
            "SELECT id, BodyType FROM BodyType ORDER BY id"
        ).fetchall()
        cur.executemany(
            "INSERT INTO body_type (id, body_type) VALUES (%s, %s)",
            rows,
        )

        # Explicit IDs were inserted into an identity column. Move the identity
        # sequence past the imported IDs before the application creates a new body type.
        cur.execute(
            """
            SELECT setval(
                pg_get_serial_sequence('body_type', 'id'),
                COALESCE((SELECT MAX(id) FROM body_type), 1),
                EXISTS (SELECT 1 FROM body_type)
            )
            """
        )


CAR_INSERT_SQL = """
    INSERT INTO cars (
        car_id,
        make,
        model,
        year,
        km,
        gear,
        fuel_type_id,
        vin,
        free_text_model,
        reg_no,
        location,
        url,
        latitude,
        longitude,
        image_link,
        dealer_segment_id,
        organisation_name,
        ad_timestamp,
        body_type_id,
        first_seen_at,
        ad_status,
        ad_status_changed_at,
        ad_status_detail,
        outcome,
        outcome_source,
        vehicle_status,
        vehicle_status_checked_at,
        ownership_changed,
        ownership_checked_at
    )
    VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
"""


def car_row_to_pg(row: sqlite3.Row, *, inactive: bool):
    return (
        as_int(row["car_id"], "car_id", nullable=False),
        row["make"],
        row["model"],
        row["year"],
        row["km"],
        row["gear"],
        normalize_fuel_type_id(row["fuelTypeId"]),
        row["vin"],
        row["freeTextModel"],
        row["regNo"],
        row["location"],
        row["url"],
        row["latitude"],
        row["longitude"],
        row["imagelink"],
        as_int(row["dealerSegmentId"], "dealerSegmentId"),
        row["organisationName"],
        as_int(row["adTimestamp"], "adTimestamp"),
        as_int(row["bodyTypeId"], "bodyTypeId"),
        sqlite_datetime(row["timestamp"]),
        "inactive" if inactive else "active",
        sqlite_datetime(row["inactivated_timestamp"]) if inactive else None,
        "legacy_inactive" if inactive else None,
        None,
        None,
        None,
        None,
        None,
        None,
    )


def migrate_cars(sqlite: sqlite3.Connection, pg: psycopg.Connection) -> None:
    active_rows = sqlite.execute(
        """
        SELECT
            car_id, make, model, year, km, gear, fuelTypeId, vin,
            freeTextModel, regNo, location, url, latitude, longitude,
            imagelink, dealerSegmentId, organisationName, adTimestamp,
            bodyTypeId, timestamp
        FROM cars
        ORDER BY id
        """
    ).fetchall()

    inactive_rows = sqlite.execute(
        """
        SELECT
            i.car_id, i.make, i.model, i.year, i.km, i.gear, i.fuelTypeId, i.vin,
            i.freeTextModel, i.regNo, i.location, i.url, i.latitude, i.longitude,
            i.imagelink, i.dealerSegmentId, i.organisationName, i.adTimestamp,
            i.bodyTypeId, i.timestamp, i.inactivated_timestamp
        FROM inactivecars i
        LEFT JOIN cars c ON c.car_id = i.car_id
        WHERE c.car_id IS NULL
        ORDER BY i.id
        """
    ).fetchall()

    with pg.cursor() as cur:
        cur.executemany(
            CAR_INSERT_SQL,
            (car_row_to_pg(row, inactive=False) for row in active_rows),
        )
        cur.executemany(
            CAR_INSERT_SQL,
            (car_row_to_pg(row, inactive=True) for row in inactive_rows),
        )

        orphan_rows = sqlite.execute(
            """
            SELECT
                p.car_id,
                MIN(p.timestamp) AS first_seen_at
            FROM prices p
            LEFT JOIN cars c ON c.car_id = p.car_id
            LEFT JOIN inactivecars i ON i.car_id = p.car_id
            WHERE c.car_id IS NULL
              AND i.car_id IS NULL
            GROUP BY p.car_id
            ORDER BY p.car_id
            """
        ).fetchall()

        cur.executemany(
            CAR_INSERT_SQL,
            (
                (
                    as_int(row["car_id"], "orphan car_id", nullable=False),
                    None, None, None, None, None, None, None, None, None,
                    None, None, None, None, None, None, None, None, None,
                    sqlite_datetime(row["first_seen_at"]),
                    "inactive",
                    None,
                    "legacy_orphan",
                    None, None, None, None, None, None,
                )
                for row in orphan_rows
            ),
        )


def migrate_prices(sqlite: sqlite3.Connection, pg: psycopg.Connection) -> None:
    rows = sqlite.execute(
        """
        SELECT car_id, price, timestamp
        FROM prices
        WHERE price IS NOT NULL
        ORDER BY id
        """
    ).fetchall()

    values = []
    for row in rows:
        price = row["price"]

        # We agreed that car prices are whole NOK. Refuse to silently round
        # unexpected decimal data.
        if price is not None and float(price) != int(float(price)):
            raise ValueError(
                f"Price {price!r} for car_id {row['car_id']!r} is not a whole NOK value"
            )

        values.append(
            (
                as_int(row["car_id"], "prices.car_id", nullable=False),
                as_int(price, "price", nullable=False),
                sqlite_datetime(row["timestamp"]),
            )
        )

    with pg.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO prices (car_id, price, timestamp)
            VALUES (%s, %s, %s)
            """,
            values,
        )


def migrate_status_progress(
    sqlite: sqlite3.Connection,
    pg: psycopg.Connection,
) -> None:
    row = sqlite.execute(
        """
        SELECT
            id,
            last_processed_car_id,
            last_run_timestamp,
            total_cars_processed,
            updated_at
        FROM status_check_progress
        WHERE id = 1
        """
    ).fetchone()

    if row is None:
        return

    with pg.cursor() as cur:
        cur.execute(
            """
            UPDATE status_check_progress
            SET last_processed_car_id = %s,
                last_run_timestamp = %s,
                total_cars_processed = %s,
                updated_at = COALESCE(%s, CURRENT_TIMESTAMP)
            WHERE id = 1
            """,
            (
                as_int(row["last_processed_car_id"], "last_processed_car_id") or 0,
                sqlite_datetime(row["last_run_timestamp"]),
                as_int(row["total_cars_processed"], "total_cars_processed") or 0,
                sqlite_datetime(row["updated_at"]),
            ),
        )


def verify_migration(sqlite: sqlite3.Connection, pg: psycopg.Connection) -> None:
    overlap = sqlite.execute(
        """
        SELECT COUNT(*)
        FROM cars c
        INNER JOIN inactivecars i ON i.car_id = c.car_id
        """
    ).fetchone()[0]

    orphan_car_ids = sqlite.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT DISTINCT p.car_id
            FROM prices p
            LEFT JOIN cars c ON c.car_id = p.car_id
            LEFT JOIN inactivecars i ON i.car_id = p.car_id
            WHERE c.car_id IS NULL
              AND i.car_id IS NULL
        )
        """
    ).fetchone()[0]

    expected = {
        "cars": (
            get_count(sqlite, "cars")
            + get_count(sqlite, "inactivecars")
            - overlap
            + orphan_car_ids
        ),
        "prices": sqlite.execute(
            "SELECT COUNT(*) FROM prices WHERE price IS NOT NULL"
        ).fetchone()[0],
        "fuel_types": get_count(sqlite, "FuelTypes"),
        "dealer_segment": get_count(sqlite, "DealerSegment"),
        "body_type": get_count(sqlite, "BodyType"),
    }

    with pg.cursor() as cur:
        actual = {}
        for table in expected:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            actual[table] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM cars WHERE ad_status = 'active'")
        actual_active = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM cars WHERE ad_status = 'inactive'")
        actual_inactive = cur.fetchone()[0]

    expected_active = get_count(sqlite, "cars")
    expected_inactive = (
        get_count(sqlite, "inactivecars")
        - overlap
        + orphan_car_ids
    )

    errors = []

    for table, expected_count in expected.items():
        if actual[table] != expected_count:
            errors.append(
                f"{table}: expected {expected_count}, got {actual[table]}"
            )

    if actual_active != expected_active:
        errors.append(
            f"active cars: expected {expected_active}, got {actual_active}"
        )

    if actual_inactive != expected_inactive:
        errors.append(
            f"inactive cars: expected {expected_inactive}, got {actual_inactive}"
        )

    if errors:
        raise RuntimeError(
            "Migration verification failed:\n  - " + "\n  - ".join(errors)
        )

    print("\nVerification:")
    print(f"  cars ............ {actual['cars']}")
    print(f"    active ........ {actual_active}")
    print(f"    inactive ...... {actual_inactive}")
    print(f"  prices .......... {actual['prices']}")
    print(f"  fuel_types ...... {actual['fuel_types']}")
    print(f"  dealer_segment .. {actual['dealer_segment']}")
    print(f"  body_type ....... {actual['body_type']}")


def main() -> int:
    sqlite_path = Path(
        os.environ.get("SQLITE_DB", str(DEFAULT_SQLITE_DB))
    )
    pg_dsn = os.environ.get("PG_DSN")

    if not sqlite_path.exists():
        print(f"SQLite database not found: {sqlite_path}", file=sys.stderr)
        return 1

    if not pg_dsn:
        print(
            "PG_DSN is not set. Example:\n"
            '  $env:PG_DSN="postgresql://prishistorie:password@localhost:5432/prishistorie"',
            file=sys.stderr,
        )
        return 1

    print(f"SQLite source: {sqlite_path}")
    print("PostgreSQL target: PG_DSN")
    print()

    sqlite = sqlite3.connect(sqlite_path)
    sqlite.row_factory = sqlite3.Row

    try:
        validate_source(sqlite)

        print("Source rows:")
        print(f"  cars ............ {get_count(sqlite, 'cars')}")
        print(f"  inactivecars .... {get_count(sqlite, 'inactivecars')}")
        print(f"  prices .......... {get_count(sqlite, 'prices')}")
        print(f"  FuelTypes ....... {get_count(sqlite, 'FuelTypes')}")
        print(f"  DealerSegment ... {get_count(sqlite, 'DealerSegment')}")
        print(f"  BodyType ........ {get_count(sqlite, 'BodyType')}")

        overlap = sqlite.execute(
            """
            SELECT COUNT(*)
            FROM cars c
            INNER JOIN inactivecars i ON i.car_id = c.car_id
            """
        ).fetchone()[0]

        orphan_car_ids = sqlite.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT DISTINCT p.car_id
                FROM prices p
                LEFT JOIN cars c ON c.car_id = p.car_id
                LEFT JOIN inactivecars i ON i.car_id = p.car_id
                WHERE c.car_id IS NULL
                  AND i.car_id IS NULL
            )
            """
        ).fetchone()[0]

        orphan_price_rows = sqlite.execute(
            """
            SELECT COUNT(*)
            FROM prices p
            LEFT JOIN cars c ON c.car_id = p.car_id
            LEFT JOIN inactivecars i ON i.car_id = p.car_id
            WHERE c.car_id IS NULL
              AND i.car_id IS NULL
            """
        ).fetchone()[0]

        print()
        print("Source reconciliation:")
        print(f"  cars/inactive overlap .. {overlap}")
        print(f"  orphan car_id .......... {orphan_car_ids}")
        fuel_zero_rows = sqlite.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM cars WHERE fuelTypeId = 0) +
                (SELECT COUNT(*) FROM inactivecars WHERE fuelTypeId = 0)
            """
        ).fetchone()[0]

        print(f"  orphan price rows ...... {orphan_price_rows}")
        print(f"  fuelTypeId 0 -> NULL ... {fuel_zero_rows}")
        print()

        # One PostgreSQL transaction: either the complete migration succeeds,
        # or it is rolled back.
        with psycopg.connect(pg_dsn) as pg:
            ensure_target_is_empty(pg)

            print("Migrating lookup tables...")
            migrate_lookup_tables(sqlite, pg)

            print("Merging cars + inactivecars...")
            migrate_cars(sqlite, pg)

            print("Migrating prices...")
            migrate_prices(sqlite, pg)

            print("Migrating status_check_progress...")
            migrate_status_progress(sqlite, pg)

            print("Verifying...")
            verify_migration(sqlite, pg)

            # The context manager commits here only if everything succeeded.

        print("\nMigration completed successfully.")
        return 0

    except Exception as exc:
        print(f"\nMigration FAILED: {exc}", file=sys.stderr)
        print("PostgreSQL changes were rolled back.", file=sys.stderr)
        return 1
    finally:
        sqlite.close()


if __name__ == "__main__":
    raise SystemExit(main())