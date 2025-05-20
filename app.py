from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import bcrypt
import mysql.connector
from mysql.connector import Error
import os

app = Flask(__name__, template_folder='.', static_folder='static')

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
# Hash the password using bcrypt
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

# Verify the hashed passwords
def check_password(stored_password: str, password: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8'))

# User class
class User(UserMixin):
    def __init__(self, username):
        self.id = username

@login_manager.user_loader
def load_user(user_id):
    try:
        # Get user from the database
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
    return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        try:
            # Connect to the database to check user credentials
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
    file = request.files.get('excel')
    if file:
        df = pd.read_excel(file)
        data = df.to_html(classes='table table-striped table-dark', index=False, border=0)
        return f"""
            <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
            <div class='container mt-5'>
                <h2 class='mb-4'>Uploaded Data (User: {current_user.id})</h2>
                {data}
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
            # Connect to the database and insert new user
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
    
    return render_template('register.html')

if __name__ == '__main__':
    app.run(host="127.0.0.1", port=5000)