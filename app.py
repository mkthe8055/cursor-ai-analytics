import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
import os
from dotenv import load_dotenv
import plotly.express as px
import numpy as np
import time
import hashlib
import json
import tempfile
import requests
import urllib.parse
from database import (
    save_data_to_db,
    load_data_from_db,
    get_current_file_info,
    delete_current_file
)

# Must be the first Streamlit command
st.set_page_config(page_title="Cursor AI Metrics Analysis", layout="wide")

# Load environment variables
load_dotenv()

# Session management functions
def get_session_file_path():
    """Get the path for storing session data"""
    temp_dir = tempfile.gettempdir()
    return os.path.join(temp_dir, "streamlit_admin_sessions.json")

def create_session_token(username):
    """Create a unique session token"""
    timestamp = str(time.time())
    return hashlib.sha256(f"{username}_{timestamp}".encode()).hexdigest()

def create_session_id():
    """Create a short session ID for URL (maps to full token)"""
    return hashlib.md5(str(time.time()).encode()).hexdigest()[:12]

def save_session(token, username, expiry_hours=24):
    """Save session token with expiration and create session ID mapping"""
    session_file = get_session_file_path()
    expiry_time = datetime.now() + timedelta(hours=expiry_hours)
    
    # Create a short session ID for the URL
    session_id = create_session_id()
    
    # Load existing sessions
    sessions = {}
    if os.path.exists(session_file):
        try:
            with open(session_file, 'r') as f:
                sessions = json.load(f)
        except:
            sessions = {}
    
    # Clean expired sessions
    current_time = datetime.now()
    sessions = {k: v for k, v in sessions.items() 
                if datetime.fromisoformat(v['expiry']) > current_time}
    
    # Add new session with both token and session_id mapping
    sessions[token] = {
        'username': username,
        'expiry': expiry_time.isoformat(),
        'created': datetime.now().isoformat(),
        'session_id': session_id
    }
    
    # Also add reverse mapping for session_id to token
    sessions[f"sid_{session_id}"] = {
        'token': token,
        'expiry': expiry_time.isoformat()
    }
    
    # Save sessions
    try:
        with open(session_file, 'w') as f:
            json.dump(sessions, f)
        return session_id  # Return session ID instead of boolean
    except:
        return None

def validate_session(token_or_session_id):
    """Validate session token or session ID"""
    if not token_or_session_id:
        return False
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return False
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        # Check if it's a session ID (shorter, needs sid_ prefix lookup)
        session_key = f"sid_{token_or_session_id}" if len(token_or_session_id) == 12 else token_or_session_id
        
        if session_key not in sessions:
            return False
        
        session = sessions[session_key]
        expiry_time = datetime.fromisoformat(session['expiry'])
        
        if datetime.now() > expiry_time:
            # Session expired, remove it and its mapping
            if session_key.startswith('sid_'):
                # Remove both session ID mapping and the actual token
                actual_token = session.get('token')
                if actual_token and actual_token in sessions:
                    del sessions[actual_token]
            else:
                # Remove token and its session ID mapping
                session_id = session.get('session_id')
                if session_id and f"sid_{session_id}" in sessions:
                    del sessions[f"sid_{session_id}"]
            
            del sessions[session_key]
            with open(session_file, 'w') as f:
                json.dump(sessions, f)
            return False
        
        return True
    except:
        return False

def get_token_from_session_id(session_id):
    """Get the actual token from session ID"""
    if not session_id:
        return None
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return None
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        session_key = f"sid_{session_id}"
        if session_key in sessions:
            return sessions[session_key].get('token')
    except:
        pass
    
    return None

def clear_session(token):
    """Clear a specific session token"""
    if not token:
        return
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        if token in sessions:
            del sessions[token]
            with open(session_file, 'w') as f:
                json.dump(sessions, f)
    except:
        pass

def get_admin_session_token():
    """Get admin session token from URL session ID or session state"""
    
    # Check URL for session ID first (for persistence across refreshes)
    query_params = st.query_params
    session_id = query_params.get("sid")
    
    if session_id and validate_session(session_id):
        # Get the actual token from session ID
        token = get_token_from_session_id(session_id)
        if token:
            # Store in session state for faster access
            st.session_state.admin_session_token = token
            return token
    
    # Check session state (for same-session access)
    if 'admin_session_token' in st.session_state:
        token = st.session_state.admin_session_token
        if validate_session(token):
            return token
        else:
            # Invalid token, clear it
            del st.session_state.admin_session_token
    
    return None

# Initialize session state
if 'upload_success' not in st.session_state:
    st.session_state.upload_success = False
if 'last_uploaded_file' not in st.session_state:
    st.session_state.last_uploaded_file = None

def authenticate_admin(username, password):
    """Authenticate admin user against environment variables"""
    return (username == os.getenv('ADMIN_USERNAME') and 
            password == os.getenv('ADMIN_PASSWORD'))

# Google OAuth functions
def get_google_auth_url():
    """Generate Google OAuth authorization URL"""
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    redirect_uri = os.getenv('REDIRECT_URI')
    
    # Ensure no trailing slash for consistency
    if redirect_uri and redirect_uri.endswith('/'):
        redirect_uri = redirect_uri[:-1]
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={client_id}&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"scope=openid email profile&"
        f"response_type=code&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    return auth_url

def exchange_code_for_token(auth_code):
    """Exchange authorization code for access token"""
    client_id = os.getenv('GOOGLE_CLIENT_ID')
    client_secret = os.getenv('GOOGLE_CLIENT_SECRET')
    redirect_uri = os.getenv('REDIRECT_URI')
    
    # Ensure no trailing slash for consistency
    if redirect_uri and redirect_uri.endswith('/'):
        redirect_uri = redirect_uri[:-1]
    
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'code': auth_code,
        'grant_type': 'authorization_code',
        'redirect_uri': redirect_uri
    }
    
    try:
        response = requests.post(token_url, data=data)
        return response.json()
    except:
        return None

def get_user_info(access_token):
    """Get user information from Google"""
    user_info_url = f"https://www.googleapis.com/oauth2/v2/userinfo?access_token={access_token}"
    
    try:
        response = requests.get(user_info_url)
        return response.json()
    except:
        return None

def is_celigo_employee(email):
    """Check if email belongs to Celigo"""
    if not email:
        return False
    return email.lower().endswith('@celigo.com')

def save_user_session(user_info, expiry_hours=24):
    """Save user session similar to admin session"""
    session_file = get_session_file_path()
    expiry_time = datetime.now() + timedelta(hours=expiry_hours)
    
    # Create session token and ID for user
    user_token = create_session_token(user_info['email'])
    session_id = create_session_id()
    
    # Load existing sessions
    sessions = {}
    if os.path.exists(session_file):
        try:
            with open(session_file, 'r') as f:
                sessions = json.load(f)
        except:
            sessions = {}
    
    # Clean expired sessions
    current_time = datetime.now()
    sessions = {k: v for k, v in sessions.items() 
                if datetime.fromisoformat(v['expiry']) > current_time}
    
    # Add new user session
    sessions[user_token] = {
        'email': user_info['email'],
        'name': user_info.get('name', ''),
        'expiry': expiry_time.isoformat(),
        'created': datetime.now().isoformat(),
        'session_id': session_id,
        'type': 'user'  # Distinguish from admin sessions
    }
    
    # Add session ID mapping
    sessions[f"user_sid_{session_id}"] = {
        'token': user_token,
        'expiry': expiry_time.isoformat()
    }
    
    # Save sessions
    try:
        with open(session_file, 'w') as f:
            json.dump(sessions, f)
        return session_id
    except:
        return None

def get_user_session_token():
    """Get user session token from URL session ID or session state"""
    
    # Check URL for user session ID first
    query_params = st.query_params
    user_session_id = query_params.get("user_sid")
    
    if user_session_id and validate_user_session(user_session_id):
        # Get the actual token from session ID
        token = get_token_from_user_session_id(user_session_id)
        if token:
            # Store in session state for faster access
            st.session_state.user_session_token = token
            return token
    
    # Check session state
    if 'user_session_token' in st.session_state:
        token = st.session_state.user_session_token
        if validate_user_session(token):
            return token
        else:
            # Invalid token, clear it
            del st.session_state.user_session_token
    
    return None

def validate_user_session(token_or_session_id):
    """Validate user session token or session ID"""
    if not token_or_session_id:
        return False
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return False
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        # Check if it's a user session ID (needs user_sid_ prefix lookup)
        session_key = f"user_sid_{token_or_session_id}" if len(token_or_session_id) == 12 else token_or_session_id
        
        if session_key not in sessions:
            return False
        
        session = sessions[session_key]
        expiry_time = datetime.fromisoformat(session['expiry'])
        
        if datetime.now() > expiry_time:
            # Session expired, remove it and its mapping
            if session_key.startswith('user_sid_'):
                # Remove both session ID mapping and the actual token
                actual_token = session.get('token')
                if actual_token and actual_token in sessions:
                    del sessions[actual_token]
            else:
                # Remove token and its session ID mapping
                session_id = session.get('session_id')
                if session_id and f"user_sid_{session_id}" in sessions:
                    del sessions[f"user_sid_{session_id}"]
            
            del sessions[session_key]
            with open(session_file, 'w') as f:
                json.dump(sessions, f)
            return False
        
        return True
    except:
        return False

def get_token_from_user_session_id(session_id):
    """Get the actual user token from session ID"""
    if not session_id:
        return None
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return None
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        session_key = f"user_sid_{session_id}"
        if session_key in sessions:
            return sessions[session_key].get('token')
    except:
        pass
    
    return None

def get_user_info_from_token(token):
    """Get user info from session token"""
    if not token:
        return None
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return None
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        if token in sessions:
            session = sessions[token]
            if session.get('type') == 'user':
                return {
                    'email': session.get('email'),
                    'name': session.get('name'),
                    'expiry': session.get('expiry')
                }
    except:
        pass
    
    return None

def clear_user_session(token):
    """Clear user session"""
    if not token:
        return
        
    session_file = get_session_file_path()
    if not os.path.exists(session_file):
        return
    
    try:
        with open(session_file, 'r') as f:
            sessions = json.load(f)
        
        if token in sessions:
            session = sessions[token]
            session_id = session.get('session_id')
            
            # Remove session ID mapping
            if session_id and f"user_sid_{session_id}" in sessions:
                del sessions[f"user_sid_{session_id}"]
            
            # Remove main session
            del sessions[token]
            
            with open(session_file, 'w') as f:
                json.dump(sessions, f)
    except:
        pass

# Check for admin route in query parameters
query_params = st.query_params
is_admin_route = query_params.get("route") == "admin"

def filter_dataframe_search(df, search_text):
    """Filter dataframe based on search text across all columns"""
    if search_text:
        mask = df.astype(str).apply(lambda x: x.str.contains(search_text, case=False)).any(axis=1)
        return df[mask]
    return df

def validate_dataframe(df):
    """Validate DataFrame structure and content"""
    errors = []
    
    # Check required columns
    required_columns = ['Date', 'Email', 'Is Active', 'Subscription Included Reqs', 'Usage Based Reqs']
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
    
    # Validate Usage Based Reqs column
    if not np.issubdtype(df['Usage Based Reqs'].dtype, np.number):
        errors.append("'Usage Based Reqs' column must contain numeric values")
    elif (df['Usage Based Reqs'] < 0).any():
        errors.append("'Usage Based Reqs' column contains negative values")
    
    # Check for empty values
    for col in required_columns:
        if df[col].isnull().any():
            errors.append(f"Empty values found in '{col}' column")
    
    return errors

def get_user_stats(filtered_df):
    """Get user statistics with manager information"""
    # First get active days count for each user
    active_days = filtered_df.groupby(['Email', filtered_df['Date'].dt.date])['Is Active'].max().reset_index()
    active_days = active_days[active_days['Is Active'] > 0].groupby('Email').size().reset_index()
    active_days.columns = ['Email', 'Active Days']
    
    # Then get other stats
    unique_users = filtered_df.groupby('Email').agg({
        'Is Active': 'max',  # True if user was active on any day
        'Subscription Included Reqs': 'sum',  # Total subscription requests
        'Usage Based Reqs': 'sum',  # Total usage based requests
        'Manager': 'first',  # Take first manager value
        'Director': 'first',  # Take first director value
        'Department': 'first'  # Take first department value
    }).reset_index()
    
    # Merge active days count with other stats
    unique_users = unique_users.merge(active_days, on='Email', how='left')
    unique_users['Active Days'] = unique_users['Active Days'].fillna(0).astype(int)  # Convert to integer
    return unique_users

# Handle Google OAuth for main dashboard (non-admin)
if not is_admin_route:
    # Check for Google OAuth callback
    query_params = st.query_params
    auth_code = query_params.get("code")
    
    if auth_code:
        # Handle OAuth callback
        token_response = exchange_code_for_token(auth_code)
        if token_response and 'access_token' in token_response:
            user_info = get_user_info(token_response['access_token'])
            if user_info and is_celigo_employee(user_info.get('email')):
                # Valid Celigo employee, create session
                user_session_id = save_user_session(user_info)
                if user_session_id:
                    st.session_state.user_session_token = get_token_from_user_session_id(user_session_id)
                    
                    # Clean up ALL OAuth parameters and only keep user_sid
                    # Clear all possible OAuth parameters
                    oauth_params_to_remove = [
                        "code", "state", "scope", "authuser", "hd", "prompt", 
                        "session_state", "access_type", "response_type"
                    ]
                    
                    # Remove all OAuth parameters
                    for param in oauth_params_to_remove:
                        if param in st.query_params:
                            del st.query_params[param]
                    
                    # Set only the user session ID
                    st.query_params.user_sid = user_session_id
                    
                    st.success("Successfully logged in!")
                    st.rerun()
                else:
                    st.error("Failed to create session")
            else:
                st.error("Access denied. Only Celigo employees can access this dashboard.")
                st.stop()
        else:
            st.error("Authentication failed. Please try again.")
            st.stop()
    
    # Check for existing user session
    user_token = get_user_session_token()
    
    if not user_token:
        # No valid session, show login
        st.markdown("""
        <style>
        .login-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            min-height: 60vh;
            padding: 2rem;
        }
        .login-title {
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 1rem;
            color: #333;
        }
        .login-subtitle {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            color: #666;
        }
        .google-btn {
            background-color: #34495e;
            color: white;
            padding: 12px 24px;
            text-decoration: none;
            border-radius: 6px;
            font-weight: 600;
            display: inline-block;
        }
        </style>
        """, unsafe_allow_html=True)
        
        # Create Google OAuth login button
        auth_url = get_google_auth_url()
        
        st.markdown(f"""
        <div class="login-container">
            <h1 class="login-title">Cursor AI Metrics Analysis</h1>
            <p class="login-subtitle">Welcome to Celigo's Cursor AI Analytics Dashboard</p>
            <p style="margin-bottom: 2rem; color: #888;">Please sign in with your Celigo Google account to access the dashboard.</p>
            <a href="{auth_url}" target="_self" class="google-btn">
                🔐 Sign with Google
            </a>
        </div>
        """, unsafe_allow_html=True)
        
        st.stop()
    
    # User is authenticated, show user info and logout option
    user_info = get_user_info_from_token(user_token)
    if user_info:
        # Add user info to sidebar
        # st.sidebar.markdown("---")
        st.sidebar.markdown(f"**👤 Logged in as:**")
        st.sidebar.markdown(f"{user_info['name']}")
        st.sidebar.markdown(f"{user_info['email']}")
        
        # Add logout button
        if st.sidebar.button("🚪 Logout", key="user_logout_btn"):
            clear_user_session(user_token)
            if 'user_session_token' in st.session_state:
                del st.session_state.user_session_token
            # Clear user session ID from URL
            if "user_sid" in st.query_params:
                del st.query_params.user_sid
            st.success("Successfully logged out!")
            st.rerun()

# Sidebar for navigation
page = st.sidebar.radio("Navigation", ["Dashboard", "Charts"])

# Handle admin route
if is_admin_route:
    st.title("Admin Panel")
    
    # Check for valid session token
    session_token = get_admin_session_token()
    
    if not session_token:
        st.info("Please login to access the admin panel")
        
        with st.form("admin_login_form"):
            username = st.text_input("Admin Username")
            password = st.text_input("Admin Password", type="password")
            login_submitted = st.form_submit_button("Admin Login")
            
            if login_submitted:
                if authenticate_admin(username, password):
                    # Create session token
                    new_token = create_session_token(username)
                    session_id = save_session(new_token, username)
                    if session_id:
                        st.session_state.admin_session_token = new_token
                        # Add session ID to URL (much shorter and safer than full token)
                        st.query_params.route = "admin"
                        st.query_params.sid = session_id
                        st.success("Successfully logged in!")
                        st.rerun()
                    else:
                        st.error("Failed to create session")
                else:
                    st.error("Invalid admin credentials")
    else:
        # Show session status
        query_params = st.query_params
        session_id = query_params.get("sid")
        
        session_file = get_session_file_path()
        if os.path.exists(session_file) and session_token:
            try:
                with open(session_file, 'r') as f:
                    sessions = json.load(f)
                if session_token in sessions:
                    session_info = sessions[session_token]
                    expiry_time = datetime.fromisoformat(session_info['expiry'])
                    time_remaining = expiry_time - datetime.now()
                    
                    if time_remaining.total_seconds() > 3600:  # More than 1 hour
                        hours_remaining = int(time_remaining.total_seconds() // 3600)
                        # st.success(f"✅ Logged in as admin (Session expires in {hours_remaining} hours) | Session ID: {session_id}")
                    else:  # Less than 1 hour
                        minutes_remaining = int(time_remaining.total_seconds() // 60)
                        # st.warning(f"⚠️ Logged in as admin (Session expires in {minutes_remaining} minutes) | Session ID: {session_id}")
            except:
                pass
        
        st.subheader("Current Data")
        current_file = get_current_file_info()
        if current_file:
            st.write(f"Last upload: {current_file['upload_date']}")
            st.write(f"Size: {current_file['size_mb']} MB")
            st.write(f"Records: {current_file['record_count']}")
            
            if st.button("Delete Current Data", key="delete_data_btn"):
                if delete_current_file():
                    st.success("Data deleted successfully!")
                    st.rerun()
        else:
            st.info("No data currently uploaded")
        
        st.subheader("Upload New Data")
        uploaded_file = st.file_uploader("Upload new Cursor AI metrics CSV file", type=["csv"])
        
        # Reset upload state if a different file is uploaded
        if uploaded_file is not None and uploaded_file != st.session_state.last_uploaded_file:
            st.session_state.upload_success = False
            st.session_state.last_uploaded_file = uploaded_file
        
        if uploaded_file is not None and not st.session_state.upload_success:
            try:
                df = pd.read_csv(uploaded_file)
                # Validate data
                errors = validate_dataframe(df)
                if errors:
                    st.error("❌ Invalid file format:")
                    for error in errors:
                        st.error(f"• {error}")
                    st.info("Please upload a valid CSV file with the correct format.")
                else:
                    with st.spinner("Processing file, please wait..."):
                        if save_data_to_db(df):
                            st.session_state.upload_success = True
                            st.success("✅ Data uploaded successfully!")
                            st.rerun()
                        else:
                            st.error("❌ Failed to upload data")
            except pd.errors.EmptyDataError:
                st.error("❌ The uploaded file is empty.")
                st.info("Please upload a CSV file containing data.")
            except pd.errors.ParserError:
                st.error("❌ Could not parse the file.")
                st.info("Please make sure you're uploading a valid CSV file.")
            except Exception as e:
                st.error(f"❌ Error processing file: {str(e)}")
                st.info("Please try uploading the file again or contact support if the issue persists.")
            
        if st.button("Logout", key="admin_logout_btn"):
            # Clear the session token
            if 'admin_session_token' in st.session_state:
                clear_session(st.session_state.admin_session_token)
                del st.session_state.admin_session_token
            
            # Clear session ID from URL
            st.query_params.route = "admin"
            if "sid" in st.query_params:
                del st.query_params.sid
            
            st.session_state.upload_success = False
            st.session_state.last_uploaded_file = None
            st.success("Successfully logged out!")
            st.rerun()

elif page == "Charts":
    st.title("Usage Analytics")
    
    # Load and filter data
    df = load_data_from_db()
    
    if df is None:
        st.warning("No data available. Please upload data in the Admin panel.")
    else:
        # Convert Date column to datetime
        df['Date'] = pd.to_datetime(df['Date'])
        
        # Add month-year column for grouping
        df['Month-Year'] = df['Date'].dt.strftime('%B %Y')
        
        # Initialize variables used across sections
        start_date = None
        end_date = None
        selected_month = None
        
        # Date range selection in sidebar
        filter_type = st.sidebar.radio(
            "Select Date Range Type",
            ["Date Range", "Month", "Until Today"]
        )
        
        if filter_type == "Date Range":
            # Get min and max dates from data
            min_date = df['Date'].dt.date.min()
            max_date = df['Date'].dt.date.max()
            
            # Create date inputs with min/max restrictions
            start_date = st.sidebar.date_input(
                "Start Date",
                value=min_date,
                min_value=min_date,
                max_value=max_date
            )
            end_date = st.sidebar.date_input(
                "End Date",
                value=max_date,
                min_value=min_date,
                max_value=max_date
            )
            
            # Validate date range
            if start_date > end_date:
                st.sidebar.error("End date must be after start date")
                start_date, end_date = end_date, start_date
            
            # Add warning if dates are outside available range
            if start_date < min_date or end_date > max_date:
                st.sidebar.warning(f"Please select dates between {min_date:%B %d, %Y} and {max_date:%B %d, %Y}")
                start_date = max(start_date, min_date)
                end_date = min(end_date, max_date)
            
            # Filter data for selected date range
            df_filtered = df[
                (df['Date'].dt.date >= start_date) & 
                (df['Date'].dt.date <= end_date)
            ].copy()
            
            # Display selected date range info
            st.caption(f"📅 Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}")
            
        elif filter_type == "Month":  # Month selection
            # Create Month-Year column with the correct date
            month_year_dates = pd.to_datetime(df['Date'])
            df['Month-Year'] = month_year_dates.dt.strftime('%B %Y')
            
            # Get unique months in reverse chronological order
            available_months = sorted(
                df['Month-Year'].unique(),
                key=lambda x: pd.to_datetime(x + " 1", format='%B %Y %d'),  # Add day for proper parsing
                reverse=True
            )
            
            selected_month = st.sidebar.selectbox(
                "Select Month",
                available_months
            )
            
            # Filter data for selected month
            month_start = pd.to_datetime(selected_month + " 1", format='%B %Y %d')
            month_end = month_start + pd.offsets.MonthEnd(0)
            
            # Filter using the full datetime to ensure correct month and year
            df_filtered = df[
                (df['Date'].dt.to_period('M') == month_start.to_period('M'))
            ].copy()
            
            # Display selected month info
            st.caption(f"📅 Showing data for: {selected_month}")
            
        else:  # Until Today
            # Calculate the earliest date from the data
            earliest_date = df['Date'].dt.date.min()
            today = datetime.now().date()
            
            # Ensure today is not beyond the max date in the data
            max_date = df['Date'].dt.date.max()
            if today > max_date:
                today = max_date
                st.sidebar.info(f"Showing data until the latest available date: {max_date:%B %d, %Y}")
            
            # Filter data from earliest date until today
            df_filtered = df[
                (df['Date'].dt.date >= earliest_date) & 
                (df['Date'].dt.date <= today)
            ].copy()
            
            # Display date range info
            st.caption(f"📅 Showing data from {earliest_date:%B %d, %Y} until {today:%B %d, %Y}")
            
            # Set start_date and end_date for later use
            start_date = earliest_date
            end_date = today
            
        # Get user statistics
        user_stats = get_user_stats(df_filtered)
        
        if isinstance(user_stats, pd.DataFrame):
            # Calculate usage percentages
            def get_usage_percentage(active_days):
                if active_days >= 20:
                    return "100% (20+ days)"
                elif active_days >= 15:
                    return "75% (15-19 days)"
                elif active_days >= 10:
                    return "50% (10-14 days)"
                elif active_days >= 5:
                    return "25% (5-9 days)"
                else:
                    return "< 25% (< 5 days)"
            
            # Add usage percentage column
            user_stats['Usage Level'] = user_stats['Active Days'].apply(get_usage_percentage)
            
            # Calculate distribution
            usage_distribution = user_stats['Usage Level'].value_counts()
            
            # Sort the index in descending order of usage percentage
            usage_levels = [
                '100% (20+ days)', 
                '75% (15-19 days)', 
                '50% (10-14 days)', 
                '25% (5-9 days)',
                '< 25% (< 5 days)'
            ]
            usage_distribution = usage_distribution.reindex(usage_levels).fillna(0)
            
            # Create color map for usage levels
            colors = {
                '100% (20+ days)': '#2ecc71',  # Green
                '75% (15-19 days)': '#3498db',  # Blue
                '50% (10-14 days)': '#f1c40f',  # Yellow
                '25% (5-9 days)': '#e67e22',    # Orange
                '< 25% (< 5 days)': '#e74c3c'   # Red
            }
            
            # Create tabs for different chart types
            chart_type = st.radio("Select Chart Type", ["Bar Chart", "Pie Chart"], horizontal=True)
            
            if chart_type == "Bar Chart":
                # Create hover text for each usage level
                hover_text = []
                for level in usage_distribution.index:
                    users_df = user_stats[user_stats['Usage Level'] == level]
                    users = users_df['Email'].astype(str).head(10).tolist()
                    hover_text.append("<br>".join(f"{i+1}. {email}" for i, email in enumerate(users)))

                # Create bar chart using Plotly
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    x=usage_distribution.index,
                    y=usage_distribution.values,
                    marker_color=[colors[level] for level in usage_distribution.index],
                    text=usage_distribution.values,
                    textposition='auto',
                    hovertemplate=(
                        "<b>%{x}</b><br>"
                        "Number of Users: %{y}<br><br>"
                        "<b>Top 10 Users:</b><br>%{customdata}<extra></extra>"
                    ),
                    customdata=hover_text
                ))
                
                fig.update_layout(
                    title={
                        'text': 'User Activity Distribution by Active Days',
                        'y': 0.95,
                        'x': 0.5,
                        'xanchor': 'center',
                        'yanchor': 'top'
                    },
                    xaxis_title="Usage Level (Based on Active Days)",
                    yaxis_title="Number of Users",
                    showlegend=False,
                    height=500,
                    plot_bgcolor='rgba(0,0,0,0)',
                    bargap=0.3,
                    hoverlabel=dict(
                        bgcolor="white",
                        font_size=12,
                        align="left"
                    )
                )
                
                # Add gridlines
                fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)')
                
                # Show the plot
                st.plotly_chart(fig, use_container_width=True)
                
            else:  # Pie Chart
                # Create hover text for each usage level
                hover_text = []
                for level in usage_distribution.index:
                    users_df = user_stats[user_stats['Usage Level'] == level]
                    users = users_df['Email'].astype(str).head(10).tolist()
                    hover_text.append("<br>".join(f"{i+1}. {email}" for i, email in enumerate(users)))

                # Calculate percentages for pie chart
                total_users = usage_distribution.sum()
                percentages = (usage_distribution / total_users * 100).round(1)
                
                # Create labels with percentages
                labels = [f"{level}<br>{pct}%" for level, pct in zip(usage_distribution.index, percentages)]
                
                # Create pie chart using Plotly
                fig = go.Figure(data=[go.Pie(
                    labels=labels,
                    values=usage_distribution.values,
                    marker_colors=[colors[level] for level in usage_distribution.index],
                    textinfo='value',
                    hovertemplate=(
                        "<b>%{label}</b><br>"
                        "Users: %{value}<br><br>"
                        "<b>Top 10 Users:</b><br>%{customdata}<extra></extra>"
                    ),
                    customdata=hover_text
                )])
                
                fig.update_layout(
                    title={
                        'text': 'User Activity Distribution by Active Days',
                        'y': 0.95,
                        'x': 0.5,
                        'xanchor': 'center',
                        'yanchor': 'top'
                    },
                    height=500,
                    hoverlabel=dict(
                        bgcolor="white",
                        font_size=12,
                        align="left"
                    )
                )
                
                # Show the plot
                st.plotly_chart(fig, use_container_width=True)
            
            st.info("""
                📊 **User Activity Categories:**
                
                • **100% Usage** (20+ days active)
                • **75% Usage** (15-19 days active)
                • **50% Usage** (10-14 days active)
                • **25% Usage** (5-9 days active)
                • **< 25% Usage** (< 5 days active)
                
                *Hover over the chart for detailed user information*
                """)
            
            # Add expandable sections for each usage category
            st.subheader("Detailed User Lists by Category")
            
            # 100% Usage Users
            with st.expander("100% Usage (20+ days active)", expanded=False):
                users_100 = user_stats[user_stats['Active Days'] >= 20]
                if not users_100.empty:
                    search_100 = st.text_input("Search in 100% Usage category", key="search_100")
                    filtered_100 = filter_dataframe_search(users_100[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_100)
                    if filtered_100.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_100.sort_values('Active Days', ascending=False), width=1200)
                else:
                    st.info("No users in this category")
            
            # 75% Usage Users
            with st.expander("75% Usage (15-19 days active)", expanded=False):
                users_75 = user_stats[(user_stats['Active Days'] >= 15) & (user_stats['Active Days'] < 20)]
                if not users_75.empty:
                    search_75 = st.text_input("Search in 75% Usage category", key="search_75")
                    filtered_75 = filter_dataframe_search(users_75[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_75)
                    if filtered_75.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_75.sort_values('Active Days', ascending=False), width=1200)
                else:
                    st.info("No users in this category")
            
            # 50% Usage Users
            with st.expander("50% Usage (10-14 days active)", expanded=False):
                users_50 = user_stats[(user_stats['Active Days'] >= 10) & (user_stats['Active Days'] < 15)]
                if not users_50.empty:
                    search_50 = st.text_input("Search in 50% Usage category", key="search_50")
                    filtered_50 = filter_dataframe_search(users_50[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_50)
                    if filtered_50.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_50.sort_values('Active Days', ascending=False), width=1200)
                else:
                    st.info("No users in this category")
            
            # 25% Usage Users
            with st.expander("25% Usage (5-9 days active)", expanded=False):
                users_25 = user_stats[(user_stats['Active Days'] >= 5) & (user_stats['Active Days'] < 10)]
                if not users_25.empty:
                    search_25 = st.text_input("Search in 25% Usage category", key="search_25")
                    filtered_25 = filter_dataframe_search(users_25[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_25)
                    if filtered_25.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_25.sort_values('Active Days', ascending=False), width=1200)
                else:
                    st.info("No users in this category")
            
            # < 25% Usage Users
            with st.expander("< 25% Usage (< 5 days active)", expanded=False):
                users_less_25 = user_stats[user_stats['Active Days'] < 5]
                if not users_less_25.empty:
                    search_less_25 = st.text_input("Search in < 25% Usage category", key="search_less_25")
                    filtered_less_25 = filter_dataframe_search(users_less_25[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_less_25)
                    if filtered_less_25.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_less_25.sort_values('Active Days', ascending=False), width=1200)
                else:
                    st.info("No users in this category")
            
            # Add spacing before next section
            st.write("")
            st.markdown("---")
            
            # Display summary statistics
            st.subheader("Activity Level Summary")
            
            # Calculate total users
            total_users = len(user_stats)
            
            # Display total users in a prominent way
            st.markdown(f"**👥 Total Users: {total_users}**")
            
            # Calculate dormant users if not already calculated
            if 'dormant_users' not in locals():
                dormant_users = df[~df['Email'].isin(user_stats['Email'])]['Email'].unique()
                total_dormant = len(dormant_users)
            
            # Calculate percentages for each category including dormant users
            highly_active = len(user_stats[user_stats['Active Days'] >= 20])
            regular_users = len(user_stats[(user_stats['Active Days'] >= 15) & (user_stats['Active Days'] < 20)])
            moderate_users = len(user_stats[(user_stats['Active Days'] >= 10) & (user_stats['Active Days'] < 15)])
            light_users = len(user_stats[(user_stats['Active Days'] >= 5) & (user_stats['Active Days'] < 10)])
            minimal_users = len(user_stats[user_stats['Active Days'] < 5])
            
            # Create columns for the metrics
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric(
                    "100% Usage",
                    f"{highly_active} users",
                    f"{(highly_active/total_users*100):.1f}%",
                    help="Users active for 20+ days"
                )
            
            with col2:
                st.metric(
                    "75% Usage",
                    f"{regular_users} users",
                    f"{(regular_users/total_users*100):.1f}%",
                    help="Users active for 15-19 days"
                )
            
            with col3:
                st.metric(
                    "50% Usage",
                    f"{moderate_users} users",
                    f"{(moderate_users/total_users*100):.1f}%",
                    help="Users active for 10-14 days"
                )
            
            with col4:
                st.metric(
                    "25% Usage",
                    f"{light_users} users",
                    f"{(light_users/total_users*100):.1f}%",
                    help="Users active for 5-9 days"
                )
            
            with col5:
                st.metric(
                    "< 25% Usage",
                    f"{minimal_users} users",
                    f"{(minimal_users/total_users*100):.1f}%",
                    help="Users active for less than 5 days"
                )
            
            # Commenting out dormant users metric
            # with col6:
            #     st.metric(
            #         "Dormant",
            #         f"{total_dormant} users",
            #         f"{(total_dormant/total_users*100):.1f}%",
            #         help="Previously active users, not seen in current period"
            #     )
            
            # Add spacing and section divider
            st.write("")
            st.markdown("---")
            
            # User Activity Analysis Section
            st.subheader("📊 Active, Inactive & Dormant Users Analysis")
            
            # Get date display based on filter type
            if filter_type == "Month":
                date_display = f"📅 Showing data for: {selected_month}"
            elif filter_type == "Until Today":
                date_display = f"📅 Showing data from {earliest_date:%B %d, %Y} until {today:%B %d, %Y}"
            else:  # Date Range
                date_display = f"📅 Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}"
            
            st.markdown(f"*{date_display}*")
            
            # Calculate user categories
            period_user_stats = get_user_stats(df_filtered)
            active_users = period_user_stats[
                (period_user_stats['Subscription Included Reqs'] > 0) | 
                (period_user_stats['Usage Based Reqs'] > 0)
            ]
            # Dormant users are those who were active (opened the app) but made no requests
            dormant_users = period_user_stats[
                (period_user_stats['Active Days'] > 0) & 
                (period_user_stats['Subscription Included Reqs'] == 0) &
                (period_user_stats['Usage Based Reqs'] == 0)
            ]
            # Inactive users are those who didn't open the app at all
            inactive_users = period_user_stats[period_user_stats['Is Active'] == 0]
            
            total_active = len(active_users)
            total_inactive = len(inactive_users)
            total_dormant = len(dormant_users)
            period_total = total_active + total_inactive + total_dormant
            
            # Display summary
            st.markdown(f"""
            👥 **User Activity Summary:**
            
            • **Active Users:** {total_active} ({(total_active/period_total*100):.1f}%) - _Users who logged in and performed actions during the selected period_
            • **Inactive Users:** {total_inactive} ({(total_inactive/period_total*100):.1f}%) - _No activity in this period_
            • **Dormant Users:** {total_dormant} ({(total_dormant/period_total*100):.1f}%) - _Used the app but not made any AI Requests_
            """)
            
            # Create figure for user status comparison
            fig = go.Figure()
            
            # Add bar traces
            fig.add_trace(go.Bar(
                x=['Active Users', 'Inactive Users', 'Dormant Users'],
                y=[total_active, total_inactive, total_dormant],
                marker_color=['#2ecc71', '#e74c3c', '#f39c12'],  # Green for active, Red for inactive, Orange for dormant
                text=[total_active, total_inactive, total_dormant],
                textposition='auto',
            ))

            # Update layout
            fig.update_layout(
                title=f"User Status Distribution - {date_display}",
                yaxis_title="Number of Users",
                showlegend=False
            )
            
            # Show the plot
            st.plotly_chart(fig, use_container_width=True)
            
            # Add expandable sections for user lists
            st.subheader("Detailed User Lists")
            
            # Display active users list
            with st.expander("View Active Users", expanded=False):
                # Get active users - those who have made either type of requests
                active_df = period_user_stats[
                    (period_user_stats['Subscription Included Reqs'] > 0) |
                    (period_user_stats['Usage Based Reqs'] > 0)
                ]
                
                if not active_df.empty:
                    search_active = st.text_input("Search active users", key="search_active")
                    filtered_active = filter_dataframe_search(active_df[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_active)
                    if filtered_active.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_active.sort_values(['Active Days', 'Email'], ascending=[False, True]), width=1200)
                else:
                    st.info("No active users found")
            
            # Inactive Users List
            with st.expander("View Inactive Users", expanded=False):
                # Get inactive users - those who didn't open the app and made no requests
                inactive_df = period_user_stats[
                    (period_user_stats['Active Days'] == 0) &
                    (period_user_stats['Subscription Included Reqs'] == 0) &
                    (period_user_stats['Usage Based Reqs'] == 0)
                ]
                
                if not inactive_df.empty:
                    search_inactive = st.text_input("Search inactive users", key="search_inactive")
                    filtered_inactive = filter_dataframe_search(inactive_df[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_inactive)
                    if filtered_inactive.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_inactive.sort_values(['Active Days', 'Email'], ascending=[False, True]), width=1200)
                else:
                    st.info("No inactive users found")
            
            # Dormant Users List
            with st.expander("View Dormant Users", expanded=False):
                # Get dormant users - those who were active but made no requests of either type
                dormant_df = period_user_stats[
                    (period_user_stats['Active Days'] > 0) & 
                    (period_user_stats['Subscription Included Reqs'] == 0) &
                    (period_user_stats['Usage Based Reqs'] == 0)
                ]
                
                if not dormant_df.empty:
                    search_dormant = st.text_input("Search dormant users", key="search_dormant")
                    filtered_dormant = filter_dataframe_search(dormant_df[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_dormant)
                    if filtered_dormant.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_dormant.sort_values(['Active Days', 'Email'], ascending=[False, True]), width=1200)
                else:
                    st.info("No dormant users found")
            
            # Add spacing before next section
            st.write("")
            st.markdown("---")

            # Active Users Analysis Section
            st.header("📈 Active Users Analysis")
            
            # Calculate active users trend
            active_by_date = df_filtered.groupby(df_filtered['Date'].dt.date).apply(
                lambda x: len(get_user_stats(x)[get_user_stats(x)['Active Days'] > 0])
            ).reset_index()
            active_by_date.columns = ['Date', 'Count']
            
            # Create trend chart
            active_trend_fig = go.Figure()
            
            # Add line trace for trend
            active_trend_fig.add_trace(go.Scatter(
                x=active_by_date['Date'],
                y=active_by_date['Count'],
                mode='lines+markers',  # Show both line and points
                line=dict(
                    color='#2ecc71',  # Green color for consistency
                    width=2
                ),
                marker=dict(
                    size=6,
                    color='#2ecc71',
                ),
                name='Active Users'
            ))

            # Update layout
            active_trend_fig.update_layout(
                title=f"Daily Active Users Trend - {date_display}",
                xaxis_title="Date",
                yaxis_title="Number of Active Users",
                showlegend=False,
                hovermode='x unified'  # Show hover for all points at same x-value
            )
            
            # Show the trend plot
            st.plotly_chart(active_trend_fig, use_container_width=True)
            
            # Add expandable section for active users list
            st.subheader("Detailed Active Users List")
            with st.expander("View All Active Users", expanded=False):
                if not active_users.empty:
                    search_active_detail = st.text_input("Search active users", key="search_active_detail")
                    filtered_active_detail = filter_dataframe_search(active_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_active_detail)
                    if filtered_active_detail.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_active_detail.sort_values(['Active Days', 'Email'], ascending=[False, True]), width=1200)
                else:
                    st.info("No active users found in this period")
            
            # Add spacing before next section
            st.write("")
            st.markdown("---")

            # Separate Inactive Users Analysis Section
            st.header("📉 Inactive Users Analysis")
            st.markdown(f"*{date_display}*")  # Add date info
            
            # Calculate inactive users trend
            inactive_by_date = df_filtered.groupby(df_filtered['Date'].dt.date).apply(
                lambda x: len(get_user_stats(x)[get_user_stats(x)['Active Days'] == 0])
            ).reset_index()
            inactive_by_date.columns = ['Date', 'Count']
            
            # Create trend chart
            trend_fig = go.Figure()
            
            # Add line trace for trend
            trend_fig.add_trace(go.Scatter(
                x=inactive_by_date['Date'],
                y=inactive_by_date['Count'],
                mode='lines+markers',  # Show both line and points
                line=dict(
                    color='#e74c3c',  # Red color for consistency
                    width=2
                ),
                marker=dict(
                    size=6,
                    color='#e74c3c',
                ),
                name='Inactive Users'
            ))

            # Update layout
            trend_fig.update_layout(
                title=f"Daily Inactive Users Trend - {date_display}",
                xaxis_title="Date",
                yaxis_title="Number of Inactive Users",
                showlegend=False,
                hovermode='x unified'  # Show hover for all points at same x-value
            )
            
            # Show the trend plot
            st.plotly_chart(trend_fig, use_container_width=True)
            
            # Add expandable section for inactive users list
            st.subheader("Detailed Inactive Users List")
            with st.expander("View All Inactive Users", expanded=False):
                if not inactive_users.empty:
                    search_inactive_detail = st.text_input("Search inactive users", key="search_inactive_detail")
                    filtered_inactive_detail = filter_dataframe_search(inactive_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']], search_inactive_detail)
                    if filtered_inactive_detail.empty:
                        st.info("No matching users found")
                    else:
                        st.dataframe(filtered_inactive_detail.sort_values(['Active Days', 'Email'], ascending=[False, True]), width=1200)
                else:
                    st.info("No inactive users found in this period")
            
            # Add spacing before next section
            st.write("")
            st.markdown("---")

        else:
            st.error("Error processing user statistics")

else:  # Dashboard page
    st.title("Cursor AI Metrics Analysis")
    
    # Reset upload success state when viewing dashboard
    st.session_state.upload_success = False
    
    # Load data
    df = load_data_from_db()
    
    if df is None:
        st.warning("No data available. Please upload data in the Admin panel.")
    else:
        # Add filters in the sidebar
        st.sidebar.subheader("Filters")
        
        # Date range filter
        st.sidebar.subheader("Date Range")
        # Convert string dates to datetime objects if needed
        if not pd.api.types.is_datetime64_any_dtype(df['Date']):
            df['Date'] = pd.to_datetime(df['Date'])
        
        # Get min and max dates as datetime.date objects
        min_date = df['Date'].dt.date.min()
        max_date = df['Date'].dt.date.max()
        
        # Create date inputs with proper date objects and min/max restrictions
        start_date = st.sidebar.date_input(
            "Start Date",
            value=min_date,
            min_value=min_date,
            max_value=max_date
        )
        end_date = st.sidebar.date_input(
            "End Date",
            value=max_date,
            min_value=min_date,
            max_value=max_date
        )
        
        # Validate date range
        if isinstance(start_date, date) and isinstance(end_date, date):
            if start_date > end_date:
                st.sidebar.error("End date must be after start date")
                start_date, end_date = end_date, start_date
            
            # Add warning if dates are outside available range
            if start_date < min_date or end_date > max_date:
                st.sidebar.warning(f"Please select dates between {min_date:%B %d, %Y} and {max_date:%B %d, %Y}")
                start_date = max(start_date, min_date)
                end_date = min(end_date, max_date)
        
        # Filter data by date range using datetime.date objects
        mask = (df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)
        df_filtered = df[mask]

        # Get user statistics for filtered data
        user_stats = get_user_stats(df_filtered)
        
        # Other filters
        search_text = st.sidebar.text_input("Search by Email")
        
        # Get unique directors for filters
        directors = sorted(user_stats['Director'].unique().tolist())
        
        selected_director = st.sidebar.selectbox(
            "Filter by Director",
            ["All"] + directors,
            index=0
        )
        
        # Display date range info and summary statistics
        st.subheader("Summary Statistics")
        
        # Format dates in a simple way
        st.caption(f"📅 Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}")
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("Total Users", len(user_stats))
        with col2:
            active_users = len(user_stats[
                (user_stats['Subscription Included Reqs'] > 0) |
                (user_stats['Usage Based Reqs'] > 0)
            ])
            st.metric("Active Users", active_users)
        with col3:
            dormant_users = len(user_stats[
                (user_stats['Active Days'] > 0) & 
                (user_stats['Subscription Included Reqs'] == 0) &
                (user_stats['Usage Based Reqs'] == 0)
            ])
            st.metric("Dormant Users", dormant_users)
        with col4:
            inactive_users = len(user_stats[
                (user_stats['Active Days'] == 0) &
                (user_stats['Subscription Included Reqs'] == 0) &
                (user_stats['Usage Based Reqs'] == 0)
            ])
            st.metric("Inactive Users", inactive_users)
        with col5:
            total_subscription_reqs = user_stats['Subscription Included Reqs'].sum()
            st.metric("Total Subscription Requests", f"{total_subscription_reqs:,}")
        with col6:
            total_usage_reqs = user_stats['Usage Based Reqs'].sum()
            st.metric("Total Usage Based Requests", f"{total_usage_reqs:,}")
            
        # Add spacing before next section
        st.write("")
        st.write("---")
        st.write("")
        
        # # Display users who exceeded 500 requests
        # high_usage_users = user_stats[
        #     (user_stats['Usage Based Reqs'] > 0) &
        #     (user_stats['Subscription Included Reqs'] > 0)
        # ]
        
        # # Apply filters to high usage users
        # filtered_high_usage = high_usage_users.copy()
        # if search_text:
        #     filtered_high_usage = filter_dataframe_search(filtered_high_usage, search_text)
        # if selected_director != "All":
        #     filtered_high_usage = filtered_high_usage[filtered_high_usage['Director'] == selected_director]
            
        # total_high_usage = len(filtered_high_usage)
        # st.subheader("Top 3 Most Active Cursor Users")
        # st.caption(f"Out of {total_high_usage} users who exceed 500 requests or using premium models")
        
        # if total_high_usage > 0:
        #     high_usage_df = filtered_high_usage[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Subscription Included Reqs', ascending=False).head(3)
        #     st.dataframe(high_usage_df, width=1200)
            
        #     # Add download button for all users (not just top 3)
        #     full_high_usage_df = filtered_high_usage[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Subscription Included Reqs', ascending=False)
        #     csv = full_high_usage_df.to_csv(index=False)
        # else:
        #     st.info("No users found with both subscription included and usage based requests in the selected date range")
            
        # Add spacing before next section
        # st.write("")
        # st.write("---")
        st.write("")
        
        # Apply filters
        filtered_stats = user_stats.copy()
        if search_text:
            filtered_stats = filter_dataframe_search(filtered_stats, search_text)
        if selected_director != "All":
            filtered_stats = filtered_stats[filtered_stats['Director'] == selected_director]
        
        # Split users into three categories
        active_users = filtered_stats[
            (filtered_stats['Subscription Included Reqs'] > 0) |
            (filtered_stats['Usage Based Reqs'] > 0)
        ]
        dormant_users = filtered_stats[
            (filtered_stats['Subscription Included Reqs'] == 0) & 
            (filtered_stats['Usage Based Reqs'] == 0) & 
            (filtered_stats['Active Days'] > 0)
        ]
        inactive_users = filtered_stats[
            (filtered_stats['Subscription Included Reqs'] == 0) & 
            (filtered_stats['Usage Based Reqs'] == 0) & 
            (filtered_stats['Active Days'] == 0)
        ]
        
        # Display active users table first
        st.subheader(f"Active Users ({len(active_users)} users)")
        st.caption("Users who have made subscription or usage based requests in the selected date range")
        st.info("""
        - **Active Days**: Number of days the user opened Cursor
        - **Subscription Included Reqs**: Number of subscription requests made to AI
        - **Usage Based Reqs**: Number of usage based requests made to AI
        """)
        if len(active_users) > 0:
            active_df = active_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Subscription Included Reqs', ascending=False)
            st.dataframe(active_df, width=1200)
            
            # Add download button
            csv = active_df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="active_users.csv",
                mime="text/csv",
            )
        else:
            st.info("No active users found with current filters")
        
        # Add spacing between tables
        st.write("")
        st.write("---")
        st.write("")
        
        # Display dormant users table
        st.subheader(f"Dormant Users ({len(dormant_users)} users)")
        st.caption("Users who opened Cursor but haven't made any subscription or usage based requests")
        st.info("""
        - **Active Days**: Number of days the user opened Cursor (but didn't make any AI requests)
        - **Subscription Included Reqs**: Will be 0 as these users haven't made any subscription requests
        - **Usage Based Reqs**: Will be 0 as these users haven't made any usage based requests
        """)
        if len(dormant_users) > 0:
            dormant_df = dormant_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Active Days', ascending=False)
            st.dataframe(dormant_df, width=1200)
            
            # Add download button
            csv = dormant_df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="dormant_users.csv",
                mime="text/csv",
            )
        else:
            st.info("No dormant users found with current filters")
            
        # Add spacing between tables
        st.write("")
        st.write("---")
        st.write("")
        
        # Display inactive users table last
        st.subheader(f"Inactive Users ({len(inactive_users)} users)")
        st.caption("Users who haven't opened Cursor at all in the selected date range")
        st.info("""
        - **Active Days**: Will be 0 as these users haven't opened Cursor
        - **Subscription Included Reqs**: Will be 0 as these users haven't made any AI requests
        """)
        if len(inactive_users) > 0:
            inactive_df = inactive_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Email')
            st.dataframe(inactive_df, width=1200)
            
            # Add download button
            csv = inactive_df.to_csv(index=False)
            st.download_button(
                label="Download as CSV",
                data=csv,
                file_name="inactive_users.csv",
                mime="text/csv",
            )
        else:
            st.info("No inactive users found with current filters") 