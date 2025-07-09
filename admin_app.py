import streamlit as st
import pandas as pd
from datetime import datetime
import os
from dotenv import load_dotenv
from pymongo import MongoClient

# Must be the first Streamlit command
st.set_page_config(page_title="Admin Panel - Cursor AI Metrics", layout="wide")

# Load environment variables
load_dotenv()

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# Initialize MongoDB connection
@st.cache(allow_output_mutation=True)
def init_mongodb():
    """Initialize MongoDB connection"""
    try:
        # Add SSL configuration to handle certificate verification
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

def authenticate_user(username, password):
    """Authenticate user against environment variables"""
    return (username == os.getenv('ADMIN_USERNAME') and 
            password == os.getenv('ADMIN_PASSWORD'))

def save_data_to_mongodb(df):
    """Save DataFrame to MongoDB"""
    if db is None:
        st.error("No MongoDB connection available")
        return False
        
    try:
        # Convert DataFrame to records
        records = df.to_dict('records')
        
        # Convert datetime to string for MongoDB storage
        for record in records:
            record['Date'] = record['Date'].strftime('%Y-%m-%dT%H:%M:%S.%fZ')
        
        # Clear existing data and insert new
        db.metrics.delete_many({})
        db.metrics.insert_many(records)
        st.success('Data successfully uploaded to database!')
        return True
    except Exception as e:
        st.error(f"Error saving data: {str(e)}")
        return False

def main():
    st.title("Admin Panel")
    
    if not st.session_state.authenticated:
        st.info("Please login to access the admin panel")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        if st.button("Login"):
            if authenticate_user(username, password):
                st.session_state.authenticated = True
                st.success("Successfully logged in!")
                st.rerun()
            else:
                st.error("Invalid credentials")
    
    if st.session_state.authenticated:
        st.subheader("Upload Data")
        uploaded_file = st.file_uploader("Upload new Cursor AI metrics CSV file", type=["csv"])
        if uploaded_file is not None:
            df = pd.read_csv(uploaded_file)
            df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%dT%H:%M:%S.%fZ', utc=True)
            df['Date'] = df['Date'].dt.date
            if save_data_to_mongodb(df):
                st.success("Data uploaded successfully! View the data at the [home page](/)")
            
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.rerun()

if __name__ == "__main__":
    main() 