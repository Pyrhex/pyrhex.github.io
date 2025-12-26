from flask import Flask, render_template, request, redirect, url_for
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import bcrypt
import mysql.connector
from mysql.connector import Error
import os
import re
import sys
from pathlib import Path
import importlib
import importlib.util
import pandas as pd
from werkzeug.middleware.dispatcher import DispatcherMiddleware

app = Flask(__name__, template_folder='.', static_folder='static')

app.secret_key = 'supersecretkey'  # Needed for session management
APPS_DIR = Path(__file__).resolve().parent / 'apps'
registered_apps = []


class LoginGuardMiddleware:
    """Protect mounted /apps/* routes so only authenticated users can access them."""

    def __init__(self, flask_app, wrapped_app, protected_prefix='/apps'):
        self._flask_app = flask_app
        self._wrapped_app = wrapped_app
        self._prefix = protected_prefix.rstrip('/') or '/'

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path and (path == self._prefix or path.startswith(f'{self._prefix}/')):
            with self._flask_app.request_context(environ):
                if not current_user.is_authenticated:
                    next_path = path or '/'
                    query = environ.get('QUERY_STRING')
                    if query:
                        next_path = f'{next_path}?{query}'
                    resp = redirect(url_for('login', next=next_path))
                    return resp(environ, start_response)
        return self._wrapped_app(environ, start_response)


def _sanitize_module_name(name: str) -> str:
    sanitized = re.sub(r'[^0-9a-zA-Z_]', '_', name)
    return sanitized or 'embedded_app'


def _friendly_name(raw: str) -> str:
    return re.sub(r'[_-]+', ' ', raw).title()


def _load_module_from_path(module_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if not spec or not spec.loader:
        raise ImportError(f'Cannot load module from {file_path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_app_module(entry: Path):
    if entry.is_dir():
        init_file = entry / '__init__.py'
        if init_file.exists():
            try:
                return importlib.import_module(f'apps.{entry.name}')
            except ModuleNotFoundError:
                pass
        app_file = entry / 'app.py'
        if app_file.exists():
            module_name = f'apps.dynamic_{_sanitize_module_name(entry.name)}'
            sys_path = str(entry.resolve())
            if sys_path not in sys.path:
                sys.path.insert(0, sys_path)
            return _load_module_from_path(module_name, app_file)
    elif entry.is_file() and entry.suffix == '.py':
        module_name = f'apps.dynamic_{_sanitize_module_name(entry.stem)}'
        sys_path = str(entry.parent.resolve())
        if sys_path not in sys.path:
            sys.path.insert(0, sys_path)
        return _load_module_from_path(module_name, entry)
    return None


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith('/') else f'{url}/'


def discover_and_register_apps(flask_app):
    """Auto-discover Flask blueprints inside the apps/ directory."""
    if not APPS_DIR.exists():
        return

    mounted_apps = {}
    for entry in sorted(APPS_DIR.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith('__'):
            continue

        module = None
        try:
            module = _load_app_module(entry)
        except Exception as exc:  # pragma: no cover - logged for debugging
            print(f'Could not import app module {entry.name}: {exc}')
            continue

        if not module:
            continue

        blueprint = getattr(module, 'app_blueprint', None)
        metadata = getattr(module, 'app_meta', None)
        app_factory = getattr(module, 'create_app', None)
        if not blueprint:
            if callable(app_factory):
                metadata = metadata or {}
                metadata.setdefault('name', _friendly_name(entry.name))
                metadata.setdefault('description', 'Custom Flask app')
                mount_path = metadata.get('mount_path') or metadata.get('url_prefix') or f'/apps/{entry.name}'
                mount_path = '/' + mount_path.strip('/')
                metadata.setdefault('url', _ensure_trailing_slash(mount_path))
                sub_app = app_factory()
                mounted_apps[mount_path.rstrip('/')] = sub_app
                registered_apps.append(metadata)
            continue

        flask_app.register_blueprint(blueprint)

        metadata = metadata or {}
        metadata.setdefault('name', _friendly_name(entry.name))
        metadata.setdefault('description', 'Custom Flask app')
        url_prefix = getattr(blueprint, 'url_prefix', f'/apps/{entry.name}')
        url_prefix = url_prefix if url_prefix.startswith('/') else f'/{url_prefix}'
        metadata.setdefault('url', _ensure_trailing_slash(url_prefix))
        registered_apps.append(metadata)

    wrapped_wsgi = flask_app.wsgi_app
    if mounted_apps:
        wrapped_wsgi = DispatcherMiddleware(flask_app.wsgi_app, mounted_apps)

    flask_app.wsgi_app = LoginGuardMiddleware(flask_app, wrapped_wsgi, '/apps')


discover_and_register_apps(app)


@app.context_processor
def inject_registered_apps():
    apps_visible = registered_apps if current_user.is_authenticated else []
    return {'registered_apps': apps_visible}

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
