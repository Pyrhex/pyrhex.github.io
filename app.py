from flask import Flask, render_template, request, redirect, url_for, flash
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
from ModMeal import _process_excel_to_rows
import tempfile
from pathlib import Path
from werkzeug.utils import secure_filename
app = Flask(__name__, template_folder='.', static_folder='static')

SCOPES = ["https://www.googleapis.com/auth/calendar"]
REDIRECT_URI = "https://realbrianlin.net/oauth2callback"
app.secret_key = 'supersecretkey'  # Needed for session management
app.config['INVOICE_UPLOAD_FOLDER'] = Path(app.static_folder) / "invoices"
app.config['ALLOWED_INVOICE_EXTENSIONS'] = {"pdf", "png", "jpg", "jpeg", "doc", "docx"}


def ensure_invoice_storage():
    app.config['INVOICE_UPLOAD_FOLDER'].mkdir(parents=True, exist_ok=True)


def get_db_connection():
    return mysql.connector.connect(
        host=os.environ.get('DB_HOST'),
        database='website',
        user=os.environ.get('DB_USER'),
        password=os.environ.get('DB_PASSWORD')
    )


def ensure_invoices_table():
    try:
        connection = get_db_connection()
        if connection.is_connected():
            cursor = connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS invoices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    original_filename VARCHAR(255) NOT NULL,
                    stored_filename VARCHAR(255) NOT NULL,
                    uploaded_by VARCHAR(255),
                    upload_date DATETIME NOT NULL,
                    paid TINYINT(1) DEFAULT 0
                )
                """
            )
            connection.commit()
            cursor.close()
        connection.close()
    except Error as e:
        print(f"Error ensuring invoices table: {e}")


def allowed_invoice_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    return filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_INVOICE_EXTENSIONS']


ensure_invoice_storage()

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
    def __init__(self, username, is_admin=False):
        self.id = username
        self.is_admin = is_admin

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
                return User(user_id, bool(user.get('is_admin', 0)))
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
                    login_user(User(username, bool(user.get('is_admin', 0))))
                    cursor.close()
                    connection.close()
                    return redirect(url_for('index'))
                cursor.close()
                connection.close()
        except Error as e:
            print(f"Error: {e}")

        flash('Invalid credentials', 'danger')

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


@app.route('/invoices')
@login_required
def invoices():
    ensure_invoices_table()
    invoices = []
    try:
        connection = get_db_connection()
        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, original_filename, stored_filename, uploaded_by, upload_date, paid FROM invoices ORDER BY upload_date DESC"
            )
            invoices = cursor.fetchall()
            cursor.close()
        connection.close()
    except Error as e:
        print(f"Error fetching invoices: {e}")
        flash('Unable to load invoices right now.', 'danger')

    return render_template('invoices.html', invoices=invoices)


@app.route('/invoices/upload', methods=['POST'])
@login_required
def upload_invoice():
    if not getattr(current_user, 'is_admin', False):
        flash('Admin privileges required.', 'danger')
        return redirect(url_for('invoices'))
    ensure_invoices_table()
    file = request.files.get('invoice_file')
    paid_status = request.form.get('paid_status', 'unpaid')
    paid = 1 if paid_status == 'paid' else 0

    if not file or file.filename == '':
        flash('Please choose an invoice to upload.', 'warning')
        return redirect(url_for('invoices'))

    if not allowed_invoice_file(file.filename):
        allowed = ", ".join(sorted(app.config['ALLOWED_INVOICE_EXTENSIONS']))
        flash(f'Unsupported file type. Allowed: {allowed}', 'warning')
        return redirect(url_for('invoices'))

    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
    original_filename = file.filename
    safe_name = secure_filename(original_filename)
    stored_filename = f"{timestamp}_{safe_name}"
    target_path = app.config['INVOICE_UPLOAD_FOLDER'] / stored_filename

    try:
        file.save(target_path)
    except Exception as e:
        print(f"Error saving invoice file: {e}")
        flash('Could not save the uploaded invoice.', 'danger')
        return redirect(url_for('invoices'))

    try:
        connection = get_db_connection()
        if connection.is_connected():
            cursor = connection.cursor()
            cursor.execute(
                "INSERT INTO invoices (original_filename, stored_filename, uploaded_by, upload_date, paid) VALUES (%s, %s, %s, %s, %s)",
                (original_filename, stored_filename, current_user.id, datetime.utcnow(), paid)
            )
            connection.commit()
            cursor.close()
        connection.close()
        flash('Invoice uploaded.', 'success')
    except Error as e:
        print(f"Error saving invoice metadata: {e}")
        target_path.unlink(missing_ok=True)
        flash('Could not record the invoice in the database.', 'danger')

    return redirect(url_for('invoices'))

@app.route('/invoices/<int:invoice_id>/status', methods=['POST'])
@login_required
def update_invoice_status(invoice_id: int):
    if not getattr(current_user, 'is_admin', False):
        flash('Admin privileges required.', 'danger')
        return redirect(url_for('invoices'))
    ensure_invoices_table()
    new_status = request.form.get('paid_status')
    if new_status not in {'paid', 'unpaid'}:
        flash('Invalid status.', 'warning')
        return redirect(url_for('invoices'))

    paid = 1 if new_status == 'paid' else 0

    try:
        connection = get_db_connection()
        if connection.is_connected():
            cursor = connection.cursor()
            cursor.execute(
                "UPDATE invoices SET paid = %s WHERE id = %s",
                (paid, invoice_id)
            )
            connection.commit()
            cursor.close()
        connection.close()
        flash('Invoice status updated.', 'success')
    except Error as e:
        print(f"Error updating invoice status: {e}")
        flash('Could not update invoice status.', 'danger')

    return redirect(url_for('invoices'))


@app.route('/invoices/<int:invoice_id>/delete', methods=['POST'])
@login_required
def delete_invoice(invoice_id: int):
    if not getattr(current_user, 'is_admin', False):
        flash('Admin privileges required.', 'danger')
        return redirect(url_for('invoices'))

    ensure_invoices_table()
    stored_filename = None
    try:
        connection = get_db_connection()
        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)
            cursor.execute(
                "SELECT stored_filename FROM invoices WHERE id = %s",
                (invoice_id,)
            )
            record = cursor.fetchone()
            if record:
                stored_filename = record['stored_filename']
                cursor.execute("DELETE FROM invoices WHERE id = %s", (invoice_id,))
                connection.commit()
            cursor.close()
        connection.close()
    except Error as e:
        print(f"Error deleting invoice: {e}")
        flash('Could not delete invoice.', 'danger')
        return redirect(url_for('invoices'))

    if stored_filename:
        file_path = app.config['INVOICE_UPLOAD_FOLDER'] / stored_filename
        try:
            file_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"Error deleting invoice file: {e}")

    flash('Invoice deleted.', 'success')
    return redirect(url_for('invoices'))


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
        flash('Registration failed. Please try again.', 'danger')
        return redirect(url_for('register'))

    return render_template('register.html')
@app.route('/manager_meals', methods=['GET', 'POST'])
def manager_meals():
    rows, error = None, None
    if request.method == 'POST':
        f = request.files.get("file")
        if not f or f.filename == "":
            error = "Please choose an .xlsx file."
        else:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                    f.save(tmp.name)
                    tmp_path = Path(tmp.name)
                rows = _process_excel_to_rows(tmp_path)
                os.unlink(tmp_path)
            except Exception as e:
                error = f"Error processing file: {e}"

    return render_template("manager_meals.html", rows=rows, error=error)
# Start the Flask app if run directly
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
