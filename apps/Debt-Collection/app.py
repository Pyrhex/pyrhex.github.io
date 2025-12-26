import os
from flask import Flask
from dotenv import load_dotenv

from pathlib import Path

from models import init_app as init_db_app
from routes import bp as routes_blueprint


def create_app() -> Flask:
    """Application factory for the debt tracking dashboard."""
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    package_root = Path(__file__).resolve().parent
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-me")
    default_db_path = package_root / "instance" / "debts.db"
    database_path = Path(os.getenv("DATABASE_PATH", str(default_db_path)))
    app.config["DATABASE"] = str(database_path)
    default_credentials = package_root / "debt-collector-481608-152c0038b659.json"
    app.config["GOOGLE_SERVICE_ACCOUNT_FILE"] = os.getenv(
        "GOOGLE_SERVICE_ACCOUNT_FILE", str(default_credentials)
    )
    app.config["GOOGLE_SHEET_ID"] = os.getenv("GOOGLE_SHEET_ID", "")
    app.config["ADMIN_PASSWORD"] = os.getenv("ADMIN_PASSWORD", "")
    app.config["PERSON_NAME"] = os.getenv("PERSON_NAME", "Friend")

    os.makedirs(app.instance_path, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    init_db_app(app)
    app.register_blueprint(routes_blueprint)

    return app


app_meta = {
    "name": "Debt Collection",
    "description": "Track shared expenses, payments, and balances.",
    "mount_path": "/apps/debt-collection",
    "url": "/apps/debt-collection/",
}

if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
