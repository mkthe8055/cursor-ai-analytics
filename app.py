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
            st.dataframe(
                active_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Subscription Included Reqs', ascending=False),
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
        st.caption("Users who opened Cursor but haven't made any subscription or usage based requests")
        st.info("""
        - **Active Days**: Number of days the user opened Cursor (but didn't make any AI requests)
        - **Subscription Included Reqs**: Will be 0 as these users haven't made any subscription requests
        - **Usage Based Reqs**: Will be 0 as these users haven't made any usage based requests
        """)
        if len(dormant_users) > 0:
            st.dataframe(
                dormant_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Active Days', ascending=False),
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
                inactive_users[['Email', 'Active Days', 'Subscription Included Reqs', 'Usage Based Reqs', 'Manager', 'Director', 'Department']].sort_values('Email'),
                width=1200
            )
        else:
            st.info("No inactive users found with current filters") 