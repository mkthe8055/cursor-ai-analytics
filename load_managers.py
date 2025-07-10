import pandas as pd
import sqlite3

def load_manager_data():
    """One-time function to load manager data into SQLite database"""
    try:
        # Read the CSV file
        df = pd.read_csv('Reporting Manager Data for Cursor AI Metrics - Sheet1.csv')
        
        # Connect to database
        db = sqlite3.connect('cursor_metrics.db')
        
        # Clear existing data
        db.execute('DELETE FROM manager_data')
        
        # Save new data
        for _, row in df.iterrows():
            db.execute('''
                INSERT INTO manager_data (email, manager, director, department)
                VALUES (?, ?, ?, ?)
            ''', (
                str(row['Work Email']),
                str(row['Manager: Name']) if pd.notna(row['Manager: Name']) else '',
                str(row['Director']) if pd.notna(row['Director']) else '',
                str(row['Department Name (from Employment)']) if pd.notna(row['Department Name (from Employment)']) else ''
            ))
        
        db.commit()
        db.close()
        print("✅ Manager data loaded successfully!")
        print("🗑️ You can now safely delete:")
        print("   - Reporting Manager Data for Cursor AI Metrics - Sheet1.csv")
        print("   - load_managers.py (this file)")
        return True
            
    except Exception as e:
        print(f"❌ Error loading manager data: {str(e)}")
        return False

if __name__ == "__main__":
    load_manager_data() 