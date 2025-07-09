import streamlit as st
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
from pymongo import MongoClient
import numpy as np

# Must be the first Streamlit command
st.set_page_config(page_title="Cursor AI Metrics Analysis", layout="wide")

# Load environment variables
load_dotenv()

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'upload_state' not in st.session_state:
    st.session_state.upload_state = None
if 'manager_data' not in st.session_state:
    st.session_state.manager_data = None

# Initialize MongoDB connection
@st.cache(allow_output_mutation=True)
def init_mongodb():
    """Initialize MongoDB connection"""
    try:
        client = MongoClient(
            os.getenv('MONGODB_URI'),
            tlsAllowInvalidCertificates=True  # For development only
        )
        db = client.cursor_metrics
        return db
    except Exception as e:
        st.error(f"Failed to connect to MongoDB: {str(e)}")
        return None

db = init_mongodb()

def load_reporting_manager_data():
    """Load and process reporting manager data"""
    try:
        manager_df = pd.read_csv("Reporting Manager Data for Cursor AI Metrics.csv")
        # Clean up the data
        manager_df = manager_df.dropna(subset=['Work Email'])  # Remove rows with no email
        # Create a mapping dictionary for quick lookups
        manager_data = manager_df.set_index('Work Email').to_dict(orient='index')
        return manager_data
    except Exception as e:
        st.error(f"Error loading reporting manager data: {str(e)}")
        return None

# Load manager data at startup
if st.session_state.manager_data is None:
    st.session_state.manager_data = load_reporting_manager_data()

def authenticate_user(username, password):
    """Authenticate user against environment variables"""
    return (username == os.getenv('ADMIN_USERNAME') and 
            password == os.getenv('ADMIN_PASSWORD'))

def validate_dataframe(df):
    """Validate DataFrame structure and content"""
    errors = []
    
    # Check required columns
    required_columns = ['Date', 'Email', 'Is Active', 'Subscription Included Reqs']
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        errors.append(f"Missing required columns: {', '.join(missing_columns)}")
        return errors
    
    # Validate Date column
    try:
        df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%dT%H:%M:%S.%fZ', utc=True)
    except Exception as e:
        errors.append(f"Invalid date format in 'Date' column. Expected format: YYYY-MM-DDThh:mm:ss.sssZ")
    
    # Validate Email column
    if not df['Email'].str.contains('@').all():
        errors.append("Invalid email format found in 'Email' column")
    
    # Validate Is Active column
    if not df['Is Active'].dtype in ['bool', 'int64', 'int32']:
        errors.append("'Is Active' column must contain boolean values")
    
    # Validate Subscription Included Reqs column
    if not np.issubdtype(df['Subscription Included Reqs'].dtype, np.number):
        errors.append("'Subscription Included Reqs' column must contain numeric values")
    elif (df['Subscription Included Reqs'] < 0).any():
        errors.append("'Subscription Included Reqs' column contains negative values")
    
    # Check for empty values
    for col in required_columns:
        if df[col].isnull().any():
            errors.append(f"Empty values found in '{col}' column")
    
    return errors

def save_data_to_mongodb(df):
    """Save DataFrame to MongoDB"""
    if db is None:
        st.error("No MongoDB connection available")
        return False
        
    try:
        # Convert DataFrame to records
        records = df.to_dict('records')
        
        # Add manager and director information to each record
        if st.session_state.manager_data:
            for record in records:
                email = record['Email']
                manager_info = st.session_state.manager_data.get(email, {})
                record['Manager'] = manager_info.get('Manager: Name', '')
                record['Director'] = manager_info.get('Director', '')
                record['Department'] = manager_info.get('Department Name (from Employment)', '')
        
        # Convert datetime to string for MongoDB storage
        for record in records:
            record['Date'] = record['Date'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Clear existing data
        db.metrics_data.drop()
        
        # Save new data
        db.metrics_data.insert_many(records)
        
        # Update metadata
        file_size_mb = len(str(records)) / (1024 * 1024)  # Approximate size in MB
        metadata = {
            'upload_date': datetime.now(),
            'size_mb': round(file_size_mb, 2),
            'record_count': len(records)
        }
        
        # Update metadata
        db.metadata.drop()
        db.metadata.insert_one(metadata)
        
        return True
            
    except Exception as e:
        st.error(f"Error saving data: {str(e)}")
        return False

def get_current_file_info():
    """Get metadata of current file"""
    try:
        if db is not None:
            return db.metadata.find_one()
        return None
    except Exception as e:
        st.error(f"Error getting file metadata: {str(e)}")
        return None

def load_data_from_mongodb():
    """Load data from MongoDB"""
    if db is None:
        st.error("No MongoDB connection available")
        return None
        
    try:
        # Get records
        records = list(db.metrics_data.find({}, {'_id': 0}))
        if not records:
            return None
            
        # Convert to DataFrame
        df = pd.DataFrame(records)
        # Convert date strings back to datetime
        df['Date'] = pd.to_datetime(df['Date'])
        df['Date'] = df['Date'].dt.date
        
        # Add manager data if not present
        if st.session_state.manager_data and 'Manager' not in df.columns:
            manager_df = pd.DataFrame(st.session_state.manager_data).T
            manager_df.index.name = 'Email'
            manager_df = manager_df.reset_index()
            df = df.merge(
                manager_df[['Email', 'Manager: Name', 'Director', 'Department Name (from Employment)']],
                left_on='Email',
                right_on='Email',
                how='left'
            )
            # Rename columns to match our expected format
            df = df.rename(columns={
                'Manager: Name': 'Manager',
                'Department Name (from Employment)': 'Department'
            })
            
        # Ensure all required columns exist
        for col in ['Manager', 'Director', 'Department']:
            if col not in df.columns:
                df[col] = ''
                
        return df
    except Exception as e:
        st.error(f"Error loading data: {str(e)}")
        return None

# Get unique users and their activity status
def get_user_stats(filtered_df):
    """Get user statistics with manager information"""
    unique_users = filtered_df.groupby('Email').agg({
        'Is Active': 'any',  # True if user was active on any day
        'Subscription Included Reqs': 'sum',  # Total subscription requests
        'Manager': 'first',  # Take first manager value
        'Director': 'first',  # Take first director value
        'Department': 'first'  # Take first department value
    }).reset_index()
    return unique_users

def delete_current_file():
    """Delete current file data and metadata"""
    if db is None:
        st.error("No MongoDB connection available")
        return False
        
    try:
        # Drop the data collection
        db.metrics_data.drop()
        # Drop the metadata
        db.metadata.drop()
        return True
    except Exception as e:
        st.error(f"Error deleting file: {str(e)}")
        return False

def filter_dataframe(df, search_text, column='Email'):
    """Filter DataFrame based on search text"""
    if search_text:
        return df[df[column].str.contains(search_text, case=False, na=False)]
    return df

# Sidebar for navigation
page = st.sidebar.radio("Navigation", ["Dashboard", "Admin"])

if page == "Admin":
    st.title("Admin Panel")
    
    if not st.session_state.authenticated:
        st.info("Please login to access the admin panel")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        if st.button("Login"):
            if authenticate_user(username, password):
                st.session_state.authenticated = True
                st.success("Successfully logged in!")
                st.experimental_rerun()
            else:
                st.error("Invalid credentials")

    if st.session_state.authenticated:
        # Show current file info if exists
        current_file = get_current_file_info()
        if current_file:
            col1, col2 = st.columns([3, 1])
            with col1:
                st.info(f"""
                    **Last Upload:** {current_file['upload_date'].strftime('%Y-%m-%d %H:%M:%S')}  
                    **File Size:** {current_file['size_mb']:.1f}MB  
                    **Records:** {current_file['record_count']:,}
                """)
            with col2:
                if st.button("🗑️ Delete Current File"):
                    if delete_current_file():
                        st.success("✅ File deleted successfully!")
                        st.session_state.upload_state = None
                        st.experimental_rerun()
        
        # Upload new file section
        st.subheader("Upload New Data")
        uploaded_file = st.file_uploader("Upload Cursor AI metrics CSV file", type=["csv"])
        
        # Only process upload if file is selected and not already processed
        if uploaded_file is not None and st.session_state.upload_state != uploaded_file.name:
            # Check file size
            file_size_mb = uploaded_file.size / (1024 * 1024)
            if file_size_mb > 500:
                st.error("❌ File size exceeds 500MB limit!")
            else:
                try:
                    with st.spinner('Processing file...'):
                        # Read the CSV file
                        try:
                            df = pd.read_csv(uploaded_file)
                        except pd.errors.EmptyDataError:
                            st.error("❌ The uploaded file is empty!")
                            st.stop()
                        except pd.errors.ParserError:
                            st.error("❌ Error parsing the CSV file. Please check the file format.")
                            st.stop()
                        
                        # Validate DataFrame
                        validation_errors = validate_dataframe(df)
                        if validation_errors:
                            for error in validation_errors:
                                st.error(f"❌ {error}")
                            st.stop()
                        
                        if save_data_to_mongodb(df):
                            st.success("✅ File updated successfully!")
                            st.session_state.upload_state = uploaded_file.name
                            st.experimental_rerun()
                except Exception as e:
                    st.error(f"❌ Unexpected error: {str(e)}")

        # Reset upload state if no file is selected
        if uploaded_file is None and st.session_state.upload_state is not None:
            st.session_state.upload_state = None

        if st.button("Logout"):
            st.session_state.authenticated = False
            st.experimental_rerun()

else:  # Dashboard page
    st.title("Cursor AI Metrics Analysis")
    
    # Load and display data analysis
    df = load_data_from_mongodb()
    if df is not None:
        # Get min and max dates from the data
        min_date = min(df['Date'])
        max_date = max(df['Date'])
        
        # Date filter in a container
        with st.container():
            st.subheader("Date Filter")
            col1, col2 = st.columns([1, 1])
            with col1:
                start_date = st.date_input("Start Date", min_date)
            with col2:
                end_date = st.date_input("End Date", max_date)
        
        # Filter data based on date range
        filtered_df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
        
        # Get unique users and their activity status with manager info
        unique_users = get_user_stats(filtered_df)
        
        # Users who never used the service (no subscription requests)
        never_used = unique_users[unique_users['Subscription Included Reqs'] == 0]
        # Users who used the service (had subscription requests)
        used_service = unique_users[unique_users['Subscription Included Reqs'] > 0]
        
        # Create two tables with search in a container
        with st.container():
            st.subheader("Analysis Results")
            
            # First table: Inactive Users
            st.write(f"Users Who Haven't Used Cursor AI ({len(never_used)} users)")
            search_inactive = st.text_input("🔍 Search Inactive Users", key="search_inactive")
            filtered_never_used = filter_dataframe(never_used, search_inactive)
            
            # Select and rename columns for display
            display_df = pd.DataFrame(filtered_never_used)[['Email', 'Subscription Included Reqs', 'Manager', 'Director', 'Department']].copy()
            display_df.columns = ['Email', 'Subscription Requests', 'Manager', 'Director', 'Department']
            
            if len(filtered_never_used) > 0:
                st.dataframe(
                    display_df,
                    height=400,
                    width=1200  # Full width for better readability
                )
            else:
                st.info("No matching inactive users found")
            
            # Add some spacing between tables
            st.write("")
            st.write("---")
            st.write("")
            
            # Second table: Active Users
            st.write(f"Users Who Used Cursor AI ({len(used_service)} users)")
            search_active = st.text_input("🔍 Search Active Users", key="search_active")
            
            # Count active days per user for those who used the service
            active_df = pd.DataFrame(filtered_df)
            active_days = active_df[active_df['Is Active'] == True].groupby('Email')['Date'].nunique().reset_index()
            active_days.columns = ['Email', 'Active Days']
            
            # Merge with subscription requests and manager info
            active_days = pd.merge(
                active_days,
                pd.DataFrame(unique_users)[['Email', 'Subscription Included Reqs', 'Manager', 'Director', 'Department']], 
                on='Email', 
                how='left'
            )
            
            # Rename columns for display
            active_days.columns = [
                'Email',
                'Active Days',
                'Subscription Requests',
                'Manager',
                'Director',
                'Department'
            ]
            
            # Only show users who actually used the service
            active_days = active_days[active_days['Email'].isin(pd.DataFrame(used_service)['Email'])]
            
            # Filter based on search
            filtered_active_days = filter_dataframe(active_days, search_active)
            if len(filtered_active_days) > 0:
                st.dataframe(
                    filtered_active_days,
                    height=400,
                    width=1200  # Full width for better readability
                )
            else:
                st.info("No matching active users found")
        
        # Add summary statistics in a container
        with st.container():
            st.subheader("Summary Statistics")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col1:
                st.metric("Total Users", len(unique_users))
            with col2:
                st.metric("Users Who Used Cursor AI", len(used_service))
            with col3:
                st.metric("Users Who Never Used Cursor AI", len(never_used))
    else:
        st.warning("No data available. Please upload a CSV file to begin analysis.") 