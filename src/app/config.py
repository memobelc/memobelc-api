from dotenv import load_dotenv
from os import path, environ

basedir = path.abspath(path.join(path.dirname(__file__), "../../"))
load_dotenv(path.join(basedir, ".env"))

# Em testes, usar MONGO_URI_TEST se definido (evita usar o banco oficial)
_testing = environ.get("TESTING", "").lower() in ("1", "true", "yes")
_default_mongo = environ.get("MONGO_URI_TEST") if _testing else environ.get("MONGO_URI")
if not _default_mongo and not _testing:
    _default_mongo = environ["MONGO_URI"]


class Config:
    PYTHONPATH = "src"
    MONGO_URI = _default_mongo
    SECRET_KEY = environ["SECRET_KEY"]
    ASAAS_API_KEY = environ.get("ASAAS_API_KEY")
    ASAAS_API_URL = environ.get("ASAAS_API_URL", "https://api-sandbox.asaas.com/v3")
    ASAAS_WEBHOOK_TOKEN = environ.get("ASAAS_WEBHOOK_TOKEN")
    SETTINGS_ENCRYPTION_KEY = environ.get("SETTINGS_ENCRYPTION_KEY") or environ.get("SECRET_KEY")
    GOOGLE_PLAY_PACKAGE_NAME = environ.get("GOOGLE_PLAY_PACKAGE_NAME", "com.anonymous.memobelc")
    GOOGLE_PLAY_SERVICE_ACCOUNT_JSON = environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON")
    GOOGLE_PLAY_SERVICE_ACCOUNT_FILE = environ.get("GOOGLE_PLAY_SERVICE_ACCOUNT_FILE")
    GOOGLE_PLAY_RTDN_TOKEN = environ.get("GOOGLE_PLAY_RTDN_TOKEN")
    GENAI_API_KEY = environ.get("GENAI_API_KEY")
    GENAI_MODEL = environ.get("GENAI_MODEL")

    MAIL_SERVER = environ.get("MAIL_SERVER")
    MAIL_PORT = environ.get("MAIL_PORT")
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = environ.get("MAIL_DEFAULT_SENDER")
    MAIL_SUPPRESS_SEND = _testing
    
    FRONT_BASE_URL = environ["FRONT_BASE_URL"]

    FLASK_ENV = environ.get("FLASK_ENV", "production")
    DEBUG = FLASK_ENV == "development"
    PORT = int(environ["PORT"])



