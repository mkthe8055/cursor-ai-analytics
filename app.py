import streamlit as st
import pandas as pd
from datetime import datetime

st.set_page_config(page_title="Cursor AI Metrics Analysis", layout="wide")

st.title("Cursor AI Metrics Analysis")

# File upload
uploaded_file = st.file_uploader("Upload your Cursor AI metrics CSV file", type=["csv"])

if uploaded_file is not None:
    # Read the CSV file
    df = pd.read_csv(uploaded_file)
    
    # Convert Date column to datetime with proper parsing of ISO format
    df['Date'] = pd.to_datetime(df['Date'], format='%Y-%m-%dT%H:%M:%S.%fZ', utc=True)
    # Convert to local timezone and get date only
    df['Date'] = df['Date'].dt.date
    
    # Get min and max dates from the data
    min_date = min(df['Date'])
    max_date = max(df['Date'])
    
    # Date filter
    st.subheader("Date Filter")
    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("Start Date", min_date)
    with col2:
        end_date = st.date_input("End Date", max_date)
    
    # Filter data based on date range
    filtered_df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
    
    # Get unique users and their activity status
    unique_users = filtered_df.groupby('Email').agg({
        'Is Active': 'any',  # True if user was active on any day
        'Subscription Included Reqs': 'sum'  # Total subscription requests
    }).reset_index()
    
    # Users who never used the service (no subscription requests)
    never_used = unique_users[unique_users['Subscription Included Reqs'] == 0]
    # Users who used the service (had subscription requests)
    used_service = unique_users[unique_users['Subscription Included Reqs'] > 0]
    
    # Create two tables
    st.subheader("Analysis Results")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"Users Who Haven't Used Cursor AI ({len(never_used)} users)")
        display_cols = ['Email', 'Subscription Included Reqs']
        st.dataframe(never_used[display_cols].sort_values('Email'), use_container_width=True)
        
    with col2:
        st.write(f"Users Who Used Cursor AI ({len(used_service)} users)")
        # Count active days per user for those who used the service
        active_days = filtered_df[filtered_df['Is Active'] == True].groupby('Email')['Date'].nunique().reset_index()
        active_days.columns = ['Email', 'Active Days']
        
        # Merge with subscription requests
        active_days = active_days.merge(
            unique_users[['Email', 'Subscription Included Reqs']], 
            on='Email', 
            how='left'
        )
        
        # Only show users who actually used the service
        active_days = active_days[active_days['Email'].isin(used_service['Email'])]
        active_days = active_days.sort_values(['Active Days', 'Subscription Included Reqs'], ascending=[False, False])
        
        st.dataframe(active_days, use_container_width=True)

    # Add summary statistics
    st.subheader("Summary Statistics")
    total_users = len(unique_users)
    users_who_used = len(used_service)
    users_who_never_used = len(never_used)
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Users", total_users)
    with col2:
        st.metric("Users Who Used Cursor AI", users_who_used)
    with col3:
        st.metric("Users Who Never Used Cursor AI", users_who_never_used)
        
    # Verification
    if users_who_used + users_who_never_used != total_users:
        st.error("Error in user count calculation! Please check the data.") 