import sqlite3
from datetime import datetime
import pandas as pd

def get_db():
    """Get SQLite database connection"""
    db = sqlite3.connect('cursor_metrics.db')
    db.row_factory = sqlite3.Row
    return db

def init_db():
    """Initialize database schema"""
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS metrics_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        email TEXT NOT NULL,
        is_active INTEGER NOT NULL,
        subscription_included_reqs INTEGER NOT NULL,
        manager TEXT,
        director TEXT,
        department TEXT
    )''')
    
    db.execute('''CREATE TABLE IF NOT EXISTS metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        upload_date TEXT NOT NULL,
        size_mb REAL NOT NULL,
        record_count INTEGER NOT NULL
    )''')

    # Manager data table
    db.execute('''CREATE TABLE IF NOT EXISTS manager_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        manager TEXT,
        director TEXT,
        department TEXT
    )''')
    
    db.commit()
    db.close()

def get_manager_info(email):
    """Get manager info for a given email"""
    try:
        db = get_db()
        row = db.execute('SELECT * FROM manager_data WHERE email = ?', (email,)).fetchone()
        db.close()
        if row:
            return {
                'Manager': row['manager'],
                'Director': row['director'],
                'Department': row['department']
            }
        return {'Manager': '', 'Director': '', 'Department': ''}
    except Exception as e:
        print(f"Error getting manager info: {str(e)}")
        return {'Manager': '', 'Director': '', 'Department': ''}

def save_data_to_db(df):
    """Save DataFrame to SQLite database"""
    try:
        # Convert DataFrame to records
        records = df.to_dict('records')
        
        # Add manager and director information to each record
        for record in records:
            email = record['Email']
            manager_info = get_manager_info(email)
            record['Manager'] = manager_info['Manager']
            record['Director'] = manager_info['Director']
            record['Department'] = manager_info['Department']
        
        # Convert datetime to string
        for record in records:
            record['Date'] = record['Date'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        db = get_db()
        # Clear existing data
        db.execute('DELETE FROM metrics_data')
        
        # Save new data
        for record in records:
            db.execute('''
                INSERT INTO metrics_data (date, email, is_active, subscription_included_reqs, manager, director, department)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                record['Date'],
                record['Email'],
                record['Is Active'],
                record['Subscription Included Reqs'],
                record['Manager'],
                record['Director'],
                record['Department']
            ))
        
        # Update metadata
        file_size_mb = len(str(records)) / (1024 * 1024)  # Approximate size in MB
        db.execute('DELETE FROM metadata')
        db.execute('''
            INSERT INTO metadata (upload_date, size_mb, record_count)
            VALUES (?, ?, ?)
        ''', (
            datetime.now().isoformat(),
            round(file_size_mb, 2),
            len(records)
        ))
        
        db.commit()
        db.close()
        return True
            
    except Exception as e:
        print(f"Error saving data: {str(e)}")
        return False

def get_current_file_info():
    """Get metadata of current file"""
    try:
        db = get_db()
        row = db.execute('SELECT * FROM metadata ORDER BY id DESC LIMIT 1').fetchone()
        db.close()
        return dict(row) if row else None
    except Exception as e:
        print(f"Error getting file metadata: {str(e)}")
        return None

def load_data_from_db():
    """Load data from SQLite database"""
    try:
        db = get_db()
        # Get records
        cursor = db.execute('SELECT * FROM metrics_data')
        records = [dict(row) for row in cursor.fetchall()]
        db.close()
        
        if not records:
            return None
            
        # Convert to DataFrame
        df = pd.DataFrame(records)
        # Convert date strings back to datetime
        df['Date'] = pd.to_datetime(df['date'])
        df['Date'] = df['Date'].dt.date
        df['Email'] = df['email']
        df['Is Active'] = df['is_active'].astype(bool)
        df['Subscription Included Reqs'] = df['subscription_included_reqs']
        df['Manager'] = df['manager']
        df['Director'] = df['director']
        df['Department'] = df['department']
        
        # Drop SQLite-specific columns
        df = df.drop(columns=['id', 'date', 'email', 'is_active', 'subscription_included_reqs', 'manager', 'director', 'department'])
        
        return df
    except Exception as e:
        print(f"Error loading data: {str(e)}")
        return None

def delete_current_file():
    """Delete current file data and metadata"""
    try:
        db = get_db()
        db.execute('DELETE FROM metrics_data')
        db.execute('DELETE FROM metadata')
        db.commit()
        db.close()
        return True
    except Exception as e:
        print(f"Error deleting file: {str(e)}")
        return False

# Initialize database
init_db() 