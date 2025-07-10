import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, date
import os
from dotenv import load_dotenv
import plotly.express as px
import numpy as np
import time
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

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'upload_success' not in st.session_state:
    st.session_state.upload_success = False
if 'last_uploaded_file' not in st.session_state:
    st.session_state.last_uploaded_file = None

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

def get_user_stats(filtered_df):
    """Get user statistics with manager information"""
    # First get active days count for each user
    active_days = filtered_df.groupby('Email')['Is Active'].apply(lambda x: x.sum()).reset_index()
    active_days.columns = ['Email', 'Active Days']
    
    # Then get other stats
    unique_users = filtered_df.groupby('Email').agg({
        'Is Active': 'any',  # True if user was active on any day
        'Subscription Included Reqs': 'sum',  # Total subscription requests
        'Manager': 'first',  # Take first manager value
        'Director': 'first',  # Take first director value
        'Department': 'first'  # Take first department value
    }).reset_index()
    
    # Merge active days count with other stats
    unique_users = unique_users.merge(active_days, on='Email', how='left')
    return unique_users

def filter_dataframe(df, search_text, column='Email'):
    """Filter DataFrame based on search text"""
    if search_text:
        return df[df[column].str.contains(search_text, case=False, na=False)]
    return df

# Sidebar for navigation
page = st.sidebar.radio("Navigation", ["Dashboard", "Charts", "Admin"])

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
        st.subheader("Current Data")
        current_file = get_current_file_info()
        if current_file:
            st.write(f"Last upload: {current_file['upload_date']}")
            st.write(f"Size: {current_file['size_mb']} MB")
            st.write(f"Records: {current_file['record_count']}")
            
            if st.button("Delete Current Data"):
                if delete_current_file():
                    st.success("Data deleted successfully!")
                    st.experimental_rerun()
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
                            st.experimental_rerun()
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
            
        if st.button("Logout"):
            st.session_state.authenticated = False
            st.session_state.upload_success = False
            st.session_state.last_uploaded_file = None
            st.experimental_rerun()

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
        
        # Sidebar filters
        st.sidebar.subheader("Time Range Selection")
        filter_type = st.sidebar.radio("Select Filter Type", ["Date Range", "Month"])
        
        if filter_type == "Date Range":
            # Date range filter
            min_date = df['Date'].min().date()
            max_date = df['Date'].max().date()
            start_date = st.sidebar.date_input("Start Date", value=min_date)
            end_date = st.sidebar.date_input("End Date", value=max_date)
            
            if isinstance(start_date, date) and isinstance(end_date, date):
                if start_date > end_date:
                    st.sidebar.error("End date must be after start date")
                    start_date, end_date = end_date, start_date
                
                # Convert start_date and end_date to datetime for comparison
                start_datetime = pd.to_datetime(start_date)
                end_datetime = pd.to_datetime(end_date)
                
                # Filter data by date range
                df_filtered = df[
                    (df['Date'] >= start_datetime) & 
                    (df['Date'] <= end_datetime)
                ].copy()
                
                # Display date range info
                st.caption(f"📅 Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}")
        else:  # Month selection
            # Get unique months in reverse chronological order
            available_months = sorted(df['Month-Year'].unique(), 
                                   key=lambda x: pd.to_datetime(x, format='%B %Y'), 
                                   reverse=True)
            
            selected_month = st.sidebar.selectbox(
                "Select Month",
                available_months
            )
            
            # Get first and last day of selected month
            selected_date = pd.to_datetime(selected_month, format='%B %Y')
            start_date = selected_date.replace(day=1).date()
            end_date = (selected_date + pd.offsets.MonthEnd(0)).date()
            
            # Filter data for selected month
            df_filtered = df[df['Month-Year'] == selected_month].copy()
            
            # Display selected month info
            st.caption(f"📅 Showing data for: {selected_month}")
        
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
                else:
                    return "< 50% (< 10 days)"
            
            # Add usage percentage column
            user_stats['Usage Level'] = user_stats['Active Days'].apply(get_usage_percentage)
            
            # Calculate distribution
            usage_distribution = user_stats['Usage Level'].value_counts()
            
            # Sort the index in descending order of usage percentage
            usage_levels = ['100% (20+ days)', '75% (15-19 days)', '50% (10-14 days)', '< 50% (< 10 days)']
            usage_distribution = usage_distribution.reindex(usage_levels).fillna(0)
            
            # Create color map for usage levels
            colors = {
                '100% (20+ days)': '#2ecc71',  # Green
                '75% (15-19 days)': '#3498db',  # Blue
                '50% (10-14 days)': '#f1c40f',  # Yellow
                '< 50% (< 10 days)': '#e74c3c'  # Red
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
                
                • **Highly Active** (20+ days active)
                • **Regular Users** (15-19 days active)
                • **Moderate Users** (10-14 days active)
                • **Low Activity** (1-9 days active)
                
                *Hover over the chart for detailed user information*
                """)
            
            # Display summary statistics
            st.subheader("Activity Level Summary")
            
            # Calculate total users
            total_users = len(user_stats)
            
            # Display total users in a prominent way
            st.markdown(f"**👥 Total Users: {total_users}**")
            st.markdown("---")
            
            # Display usage level statistics
            stats_cols = st.columns(4)
            with stats_cols[0]:
                active_users = len(user_stats[user_stats['Active Days'] >= 20])
                percentage = (active_users / total_users * 100) if total_users > 0 else 0
                st.metric("100% Usage", 
                         f"{active_users} ({percentage:.1f}%)",
                         help="Users active for 20+ days per month")
            with stats_cols[1]:
                regular_users = len(user_stats[(user_stats['Active Days'] >= 15) & (user_stats['Active Days'] < 20)])
                percentage = (regular_users / total_users * 100) if total_users > 0 else 0
                st.metric("75% Usage", 
                         f"{regular_users} ({percentage:.1f}%)",
                         help="Users active for 15-19 days per month")
            with stats_cols[2]:
                moderate_users = len(user_stats[(user_stats['Active Days'] >= 10) & (user_stats['Active Days'] < 15)])
                percentage = (moderate_users / total_users * 100) if total_users > 0 else 0
                st.metric("50% Usage", 
                         f"{moderate_users} ({percentage:.1f}%)",
                         help="Users active for 10-14 days per month")
            with stats_cols[3]:
                occasional_users = len(user_stats[user_stats['Active Days'] < 10])
                percentage = (occasional_users / total_users * 100) if total_users > 0 else 0
                st.metric("< 50% Usage", 
                         f"{occasional_users} ({percentage:.1f}%)",
                         help="Users active for less than 10 days per month")

            # Inactive Users Analysis
            st.markdown("---")
            st.subheader("📉 Inactive Users Analysis")
            
            # Calculate the earliest date from the data
            earliest_date = df['Date'].min().date()
            today = datetime.now().date()

            # Date range selection
            inactive_date_option = st.radio(
                "Select Date Range",
                ["Selected Date Range", "Until Today"],
                key="inactive_date_option"
            )

            # Get the filtered dataframe based on date range
            if inactive_date_option == "Selected Date Range":
                # Use the filtered dataframe from sidebar date range
                df_inactive_period = df_filtered.copy()
                if filter_type == "Month":
                    date_display = f"Showing data for: {selected_month}"
                else:
                    date_display = f"Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}"
            else:  # Until Today
                df_inactive_period = df[
                    (df['Date'].dt.date >= earliest_date) & 
                    (df['Date'].dt.date <= today)
                ]
                date_display = f"Showing data from {earliest_date:%B %d, %Y} until today ({today:%B %d, %Y})"
            
            st.markdown(f"*{date_display}*")
            
            # Calculate inactive users
            inactive_user_stats = get_user_stats(df_inactive_period)
            inactive_users = inactive_user_stats[inactive_user_stats['Active Days'] == 0]
            total_inactive = len(inactive_users)

            if total_inactive > 0:
                # Display summary
                total_users = len(inactive_user_stats)
                st.markdown(f"""
                👥 **Total Users: {total_users}**
                
                🚫 **Total Inactive Users: {total_inactive}** ({(total_inactive/total_users*100):.1f}% of total users)
                
                Inactive users are those who have 0 active days during the selected time period.
                """)
                
                # Create bar chart for inactive distribution
                fig = go.Figure()
                
                # Format date range for x-axis label
                if inactive_date_option == "Selected Date Range":
                    x_axis_label = f"{start_date:%b %d} - {end_date:%b %d, %Y}"
                else:
                    x_axis_label = f"Until {today:%b %d, %Y}"

                # Get top 10 inactive users
                top_10_inactive = inactive_users.sort_values(by='Email').head(10)['Email'].tolist()
                hover_text = "<br>".join(f"{i+1}. {email}" for i, email in enumerate(top_10_inactive))
                
                fig.add_trace(go.Bar(
                    name="Inactive Users",
                    x=[x_axis_label],
                    y=[total_inactive],
                    text=f"{total_inactive}",
                    textposition='auto',
                    marker_color='#e74c3c',
                    width=0.5,
                    hoverlabel=dict(
                        bgcolor='#2c3e50',  # Dark blue-grey background
                        font_size=14,
                        font_family="Arial"
                    ),
                    hovertemplate=(
                        "<b>Total Inactive Users: %{y}</b><br><br>"
                        "<b>Top 10 Inactive Users:</b><br>"
                        + hover_text
                        + ("<br><br>...and more" if len(inactive_users) > 10 else "")
                        + "<extra></extra>"
                    )
                ))

                # Update layout
                fig.update_layout(
                    title={
                        'text': 'Distribution of Inactive Users',
                        'y': 0.95,
                        'x': 0.5,
                        'xanchor': 'center',
                        'yanchor': 'top'
                    },
                    xaxis_title="Time Range",
                    yaxis_title="Number of Inactive Users",
                    showlegend=False,
                    height=400,
                    plot_bgcolor='rgba(0,0,0,0)',
                    bargap=0.3,
                    xaxis=dict(
                        tickangle=0,
                        tickfont=dict(size=12)
                    )
                )
                
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.success("🎉 Great news! There are no inactive users (0 active days) in the selected time period.")

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
        
        # Create date inputs with proper date objects
        start_date = st.sidebar.date_input("Start Date", value=min_date)
        end_date = st.sidebar.date_input("End Date", value=max_date)
        
        # Validate date range
        if isinstance(start_date, date) and isinstance(end_date, date):
            if start_date > end_date:
                st.sidebar.error("End date must be after start date")
                start_date, end_date = end_date, start_date
        
        # Filter data by date range using datetime.date objects
        mask = (df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)
        df_filtered = df[mask]

        # Get user statistics for filtered data
        user_stats = get_user_stats(df_filtered)
        
        # Display date range info and summary statistics
        st.subheader("Summary Statistics")
        
        # Format dates in a simple way
        st.caption(f"📅 Showing data for: {start_date:%B %d, %Y} to {end_date:%B %d, %Y}")
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Users", len(user_stats))
        with col2:
            active_users = len(user_stats[user_stats['Subscription Included Reqs'] > 0])
            st.metric("Active Users", active_users)
        with col3:
            dormant_users = len(user_stats[(user_stats['Subscription Included Reqs'] == 0) & (user_stats['Active Days'] > 0)])
            st.metric("Dormant Users", dormant_users)
        with col4:
            inactive_users = len(user_stats[(user_stats['Subscription Included Reqs'] == 0) & (user_stats['Active Days'] == 0)])
            st.metric("Inactive Users", inactive_users)
        with col5:
            total_requests = user_stats['Subscription Included Reqs'].sum()
            st.metric("Total Subscription Requests", f"{total_requests:,}")
        
        # Other filters
        search_text = st.sidebar.text_input("Search by Email")
        
        # Get unique directors for filters
        directors = sorted(user_stats['Director'].unique().tolist())
        
        selected_director = st.sidebar.selectbox(
            "Filter by Director",
            ["All"] + directors,
            index=0
        )
        
        # Apply filters
        filtered_stats = user_stats.copy()
        if search_text:
            filtered_stats = filter_dataframe(filtered_stats, search_text)
        if selected_director != "All":
            filtered_stats = filtered_stats[filtered_stats['Director'] == selected_director]
        
        # Split users into three categories
        active_users = filtered_stats[filtered_stats['Subscription Included Reqs'] > 0]
        dormant_users = filtered_stats[(filtered_stats['Subscription Included Reqs'] == 0) & (filtered_stats['Active Days'] > 0)]
        inactive_users = filtered_stats[(filtered_stats['Subscription Included Reqs'] == 0) & (filtered_stats['Active Days'] == 0)]
        
        # Display active users table first
        st.subheader(f"Active Users ({len(active_users)} users)")
        st.caption("Users who have made subscription requests in the selected date range")
        st.info("""
        - **Active Days**: Number of days the user opened Cursor
        - **Subscription Included Reqs**: Number of requests made to AI
        """)
        if len(active_users) > 0:
            st.dataframe(
                active_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Manager', 'Director', 'Department']].sort_values('Subscription Included Reqs', ascending=False),
                width=1200
            )
        else:
            st.info("No active users found with current filters")
        
        # Add spacing between tables
        st.write("")
        st.write("---")
        st.write("")
        
        # Display dormant users table
        st.subheader(f"Dormant Users ({len(dormant_users)} users)")
        st.caption("Users who opened Cursor but haven't made any subscription requests")
        st.info("""
        - **Active Days**: Number of days the user opened Cursor (but didn't make AI requests)
        - **Subscription Included Reqs**: Will be 0 as these users haven't made any AI requests
        """)
        if len(dormant_users) > 0:
            st.dataframe(
                dormant_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Manager', 'Director', 'Department']].sort_values('Active Days', ascending=False),
                width=1200
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
            st.dataframe(
                inactive_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Manager', 'Director', 'Department']].sort_values('Email'),
                width=1200
            )
        else:
            st.info("No inactive users found with current filters") 