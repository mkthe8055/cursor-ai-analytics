import requests
import pandas as pd
from datetime import datetime, timezone
import os
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

def get_cursor_api_data(start_date_epoch=None, end_date_epoch=None):
    """
    Fetch data from Cursor API
    
    Args:
        start_date_epoch (int): Start date in epoch time (defaults to env variable)
        end_date_epoch (int): End date in epoch time (defaults to today)
    
    Returns:
        dict: API response data or None if error
    """
    api_key = os.getenv('CURSOR_API_KEY')
    api_url = os.getenv('CURSOR_API_URL', 'https://api.cursor.com/teams/daily-usage-data')
    
    if not api_key:
        raise ValueError("CURSOR_API_KEY not found in environment variables")
    
    # Use default start date from env if not provided
    if start_date_epoch is None:
        start_date_epoch = int(os.getenv('CURSOR_START_DATE_EPOCH', '1746057600'))
    
    # Use today's date as end date if not provided
    if end_date_epoch is None:
        end_date_epoch = int(time.time())
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    try:
        print(f"Fetching data from {api_url}")
        print(f"Date range: {datetime.fromtimestamp(start_date_epoch)} to {datetime.fromtimestamp(end_date_epoch)}")
        
        # Use POST request with data in the body
        data = {
            'startDate': start_date_epoch * 1000,  # Convert to milliseconds
            'endDate': end_date_epoch * 1000       # Convert to milliseconds
        }
        
        response = requests.post(api_url, headers=headers, json=data)
        response.raise_for_status()
        
        return response.json()
    
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Cursor API: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None

def transform_cursor_data_to_dataframe(api_data):
    """
    Transform Cursor API data to the expected DataFrame format
    
    Args:
        api_data (dict): Raw API response data
    
    Returns:
        pd.DataFrame: Transformed data with columns: Date, Email, Is Active, Subscription Included Reqs, Usage Based Reqs
    """
    if not api_data or 'data' not in api_data:
        print("No data found in API response")
        return pd.DataFrame()
    
    records = []
    
    for entry in api_data['data']:
        # Extract the required fields mapping from API to our expected format
        record = {
            'Date': convert_to_iso_format(entry.get('date')),
            'Email': entry.get('email', ''),
            'Is Active': bool(entry.get('isActive', False)),
            'Subscription Included Reqs': int(entry.get('subscriptionIncludedReqs', 0)),
            'Usage Based Reqs': int(entry.get('usageBasedReqs', 0))
        }
        
        # Validate that we have required data
        if record['Email'] and record['Date']:
            records.append(record)
    
    if not records:
        print("No valid records found in API data")
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    # Convert Date column to datetime
    df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%dT%H:%M:%S.%fZ', utc=True)
    
    print(f"Transformed {len(df)} records from API data")
    return df

def convert_to_iso_format(date_input):
    """
    Convert various date formats to ISO format expected by our system
    
    Args:
        date_input: Date in various formats (epoch, ISO string, etc.)
    
    Returns:
        str: Date in YYYY-MM-DDThh:mm:ss.sssZ format
    """
    if isinstance(date_input, (int, float)):
        # Handle both seconds and milliseconds epoch time
        if date_input > 1e10:  # If greater than 10 billion, assume milliseconds
            dt = datetime.fromtimestamp(date_input / 1000, tz=timezone.utc)
        else:  # Otherwise assume seconds
            dt = datetime.fromtimestamp(date_input, tz=timezone.utc)
    elif isinstance(date_input, str):
        # Try to parse ISO format or other common formats
        try:
            dt = datetime.fromisoformat(date_input.replace('Z', '+00:00'))
        except:
            # Fallback to pandas parsing
            dt = pd.to_datetime(date_input, utc=True).to_pydatetime()
    else:
        # Fallback to current time
        dt = datetime.now(timezone.utc)
    
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')

def fetch_and_save_cursor_data():
    """
    Main function to fetch data from API and save to database
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Import here to avoid circular imports
        from database import save_data_to_db
        
        print("Starting Cursor API data fetch...")
        
        # Fetch data from API
        api_data = get_cursor_api_data()
        if not api_data:
            print("Failed to fetch data from API")
            return False
        
        # Transform to DataFrame
        df = transform_cursor_data_to_dataframe(api_data)
        if df.empty:
            print("No data to save")
            return False
        
        # Save to database (this will automatically add manager info)
        success = save_data_to_db(df, data_source="api_fetch", source_filename=None)
        if success:
            print(f"Successfully saved {len(df)} records to database")
        else:
            print("Failed to save data to database")
        
        return success
        
    except Exception as e:
        print(f"Error in fetch_and_save_cursor_data: {e}")
        return False

if __name__ == "__main__":
    # For testing purposes
    success = fetch_and_save_cursor_data()
    if success:
        print("✅ Data fetch and save completed successfully")
    else:
        print("❌ Data fetch and save failed") 