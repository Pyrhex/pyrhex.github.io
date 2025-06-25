from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from googleapiclient.errors import HttpError
import re
import pandas as pd
import traceback
import bcrypt
import mysql.connector
from mysql.connector import Error
import os
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import pytz
from google_auth_oauthlib.flow import Flow
from google_cal import upload_schedule
app = Flask(__name__, template_folder='.', static_folder='static')

SCOPES = ["https://www.googleapis.com/auth/calendar"]
REDIRECT_URI = "https://realbrianlin.net/oauth2callback"
app.secret_key = 'supersecretkey'  # Needed for session management

# Flask-Login setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # redirect here if not logged in
def get_env_var(name):
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(f"Missing required environment variable: {name}")
    return value

def convert_to_24_hour(time_str):
    match = re.match(r"(\d{1,2})(:(\d{2}))?(AM|PM)", time_str, re.IGNORECASE)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(3) or 0)
    period = match.group(4).upper()

    if period == "PM" and hour != 12:
        hour += 12
    elif period == "AM" and hour == 12:
        hour = 0

    return f"{hour:02}:{minute:02}"

# Hash the password using bcrypt
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
# %%
# Verify the hashed passwords
def check_password(stored_password: str, password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8'))
# %%

# These variables need to be reused from your bot logic
TIME_RANGE_PATTERN = re.compile(r"^\d{1,2}(:\d{2})?(AM|PM) ?- ?\d{1,2}(:\d{2})?(AM|PM)$", re.IGNORECASE)
SKIP_VALUES = {"-", "OFF", "N/A", "AM ONLY"}
SKIP_KEYWORDS = ["REQ", "NO"]
names = ["Brian*", "Abdi*", "Emilyn*", "Ryan*", "Jordan", "Cindy*", "KC*", "Jojo*", "Christian*", "Troy*", "Tristan*", "Ian", "Sara"]
    
# User class
class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    try:
        connection = mysql.connector.connect(
            host=os.environ.get('DB_HOST'),
            database='website',
            user=os.environ.get('DB_USER'),
            password=os.environ.get('DB_PASSWORD')
        )
        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (user_id,))
            user = cursor.fetchone()
            cursor.close()
            connection.close()
            if user:
                return User(user_id)
    except Error as e:
        print(f"Error: {e}")
    # if user_id == "brian":
    #     return User("brian")
    # return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            connection = mysql.connector.connect(
                host=os.environ.get('DB_HOST'),
                database='website',
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD')
            )
            if connection.is_connected():
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
                user = cursor.fetchone()
                if user and check_password(user['password'], password):
                    login_user(User(username))
                    cursor.close()
                    connection.close()
                    return redirect(url_for('index'))
                else:
                    cursor.close()
                    connection.close()
                    return "Invalid credentials"
        except Error as e:
            print(f"Error: {e}")

        # if username == "brian" and password == "123":
        #     login_user(User("brian"))
        #     return redirect(url_for('index'))
        # return "Invalid credentials"

    return render_template('login.html')

@app.route('/schedule')
def schedule():
    return render_template('schedule.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    files = request.files.getlist('excel')
    if not files:
        return "No files uploaded", 400

    results = []
    for file in files:
        success, error_msg = upload_schedule(file)
        results.append((file.filename, success, error_msg))

    success_html = "".join(
        f"<li>✅ {filename}</li>" for filename, success, _ in results if success
    )
    error_html = "".join(
        f"<li>❌ {filename}: {msg}</li>" for filename, success, msg in results if not success
    )

    return f"""
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
        <div class='container mt-5'>
            <h2 class='mb-4'>Upload Results (User: {current_user.id})</h2>
            <ul>{success_html}{error_html}</ul>
            <a href="/" class="btn btn-secondary mt-3">Back to Home</a>
        </div>
    """

# Route for user registration (you can adjust this to your needs)
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        hashed_password = hash_password(password)

        try:
            connection = mysql.connector.connect(
                host=os.environ.get('DB_HOST'),
                database='website',
                user=os.environ.get('DB_USER'),
                password=os.environ.get('DB_PASSWORD')
            )
            if connection.is_connected():
                cursor = connection.cursor()
                cursor.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
                connection.commit()
                cursor.close()
                connection.close()
                return redirect(url_for('login'))
        except Error as e:
            print(f"Error: {e}")
        return redirect(url_for('login'))

    return render_template('register.html')

# Start the Flask app if run directly
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)