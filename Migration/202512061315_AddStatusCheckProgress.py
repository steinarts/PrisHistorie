import sqlite3

def run_migration(db_path):
    """
    Creates status_check_progress table for automatic batch progression tracking.
    Enables FindCarsForUpdateOfStatus to dynamically continue from last processed car_id.
    
    Changes:
    - Creates status_check_progress table (single-row tracking)
    - Adds performance index on cars.car_id
    - Inserts default tracking row (starts from car_id = 0)
    
    Benefits:
    - Eliminates manual id > 595000 adjustments
    - Enables automatic progression through 600k car backlog
    - Provides crash recovery (resumes from last saved position)
    - Tracks run statistics for monitoring
    
    @param db_path: Path to SQLite database file (str)
    @return: None
    @throws: sqlite3.Error on database failures
    @author: GitHub Copilot
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create status_check_progress tracking table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS status_check_progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_processed_car_id INTEGER DEFAULT 0,
                last_run_timestamp TEXT,
                total_cars_processed INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Insert default tracking row (starts from car_id = 0)
        cursor.execute('''
            INSERT OR IGNORE INTO status_check_progress (id, last_processed_car_id)
            VALUES (1, 0)
        ''')
        
        # Create performance index on cars.car_id for fast WHERE car_id > ? queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cars_car_id 
            ON cars(car_id)
        ''')
        
        # Create index on timestamp for efficient ordering
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_cars_timestamp 
            ON cars(timestamp)
        ''')
        
        conn.commit()
        print("✅ Migrasjon fullført: status_check_progress tabell og indexes lagt til.")
        print("📊 System klar for automatisk batch-prosessering av 600k biler!")
        
    except sqlite3.Error as e:
        conn.rollback()
        print(f"❌ Migrasjon feilet: {e}")
        raise
    
    finally:
        conn.close()

if __name__ == "__main__":
    db_path = "data/PrisHistorie.db"
    run_migration(db_path)