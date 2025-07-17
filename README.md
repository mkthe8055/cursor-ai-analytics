# Cursor AI Metrics Analysis

A Streamlit application for analyzing Cursor AI usage metrics.

## Features

- Upload and analyze Cursor AI metrics data
- View user activity and subscription request statistics
- Filter and search through user data
- Secure admin panel for data management
- Manager and department information integration
- Secure data storage in SQLite database

## Setup

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Create a `.env` file with the following variables:
   ```
   ADMIN_USERNAME=your_admin_username
   ADMIN_PASSWORD=your_admin_password
   ```

## Data Storage

The application uses SQLite for all data storage. The database file `cursor_metrics.db` will be created automatically when you first run the application. It contains the following tables:
- metrics_data: Stores user activity and subscription metrics
- metadata: Stores information about data uploads
- manager_data: Stores organizational hierarchy information (managers, directors, departments)

## Running the Application

1. Start the main application:
   ```bash
   streamlit run app.py
   ```


## Data Format

The application expects CSV files with the following columns:
- Date (format: YYYY-MM-DDThh:mm:ss.sssZ)
- Email
- Is Active (boolean)
- Subscription Included Reqs (numeric)

## Security

- Admin authentication required for data management
- All sensitive data stored securely in SQLite database
- No sensitive data exposed in source code or configuration files
- Database file should be properly secured with appropriate file permissions

## Development

The application is built with:
- Python 3.8+
- Streamlit
- Pandas
- SQLite3 (built into Python)
- python-dotenv for configuration
- bcrypt for password hashing
