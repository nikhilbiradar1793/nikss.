from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
    send_from_directory,
    send_file,
    abort,
)
import os
from flask_sqlalchemy import SQLAlchemy

from werkzeug.security import (
    generate_password_hash,
    check_password_hash,
)

from werkzeug.utils import secure_filename

from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
from datetime import datetime
from sqlalchemy import inspect, text, or_
from uuid import uuid4
import os
import razorpay

from dotenv import load_dotenv


# ============================================================
# APP CONFIGURATION
# ============================================================

# Load .env from the same directory as app.py. This makes local
# testing reliable even when Flask is started from another folder.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(dotenv_path=os.path.join(BASE_DIR, ".env"), override=False)

app = Flask(__name__)
# Render terminates HTTPS at its proxy. ProxyFix makes Flask generate
# correct https callback URLs for Google OAuth in production.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.config["SECRET_KEY"] = (
        os.getenv("FLASK_SECRET_KEY")
        or os.getenv("SECRET_KEY")
        or "nikss-coding-hub-dev-secret-change-this"
)

# Safe cookie defaults. On Render, cookies are marked Secure; locally they remain HTTP-compatible.
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.getenv("RENDER"))

app.config["SQLALCHEMY_DATABASE_URI"] = (
        "sqlite:///"
        + os.path.join(BASE_DIR, "nikss_coding_hub.db")
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Maximum uploaded video size: 500 MB
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024

VIDEO_UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "static",
    "uploads",
    "videos",
)

os.makedirs(VIDEO_UPLOAD_FOLDER, exist_ok=True)

app.config["VIDEO_UPLOAD_FOLDER"] = VIDEO_UPLOAD_FOLDER

# Course posters and site branding logos are stored in the existing
# static/uploads folder so existing course images keep working.
STATIC_UPLOAD_FOLDER = os.path.join(
    BASE_DIR,
    "static",
    "uploads",
)
os.makedirs(STATIC_UPLOAD_FOLDER, exist_ok=True)
app.config["STATIC_UPLOAD_FOLDER"] = STATIC_UPLOAD_FOLDER

ALLOWED_IMAGE_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp",
}

ALLOWED_VIDEO_EXTENSIONS = {
    "mp4",
    "webm",
    "ogg",
    "mov",
    "m4v",
}

db = SQLAlchemy(app)


# ============================================================
# GOOGLE OAUTH CONFIGURATION
# ============================================================
# Required environment variables:
# GOOGLE_CLIENT_ID
# GOOGLE_CLIENT_SECRET
#
# Redirect URI used by this application:
# https://YOUR-DOMAIN/login/google/callback
# For local development:
# http://127.0.0.1:5000/login/google/callback

GOOGLE_CLIENT_ID = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
GOOGLE_CLIENT_SECRET = (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()

# Google accounts that are allowed to access the Admin Dashboard.
# These addresses are administrators; they do not go through the
# student first-name/last-name/mobile/OTP registration flow.
DEFAULT_ADMIN_GOOGLE_EMAILS = {
    "nikhilbiradar53@gmail.com",
    "nikhilbiradar1793@gmail.com",
    "nikhilbiradar9405@gmail.com",
}
ADMIN_GOOGLE_EMAILS = {
    email.strip().lower()
    for email in os.getenv("ADMIN_GOOGLE_EMAILS", ",".join(sorted(DEFAULT_ADMIN_GOOGLE_EMAILS))).split(",")
    if email.strip()
}

oauth = OAuth(app)
google = None

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    try:
        google = oauth.register(
            name="google",
            client_id=GOOGLE_CLIENT_ID,
            client_secret=GOOGLE_CLIENT_SECRET,
            server_metadata_url=(
                "https://accounts.google.com/"
                ".well-known/openid-configuration"
            ),
            client_kwargs={
                "scope": "openid email profile"
            },
        )
        print("GOOGLE OAUTH CONFIGURED")
    except Exception as error:
        google = None
        print("Google OAuth initialization error:", repr(error))
else:
    print("WARNING: GOOGLE OAUTH KEYS NOT FOUND")
    print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET")



# ============================================================
# RAZORPAY CONFIGURATION
# ============================================================

# Render does NOT use your local .env file automatically.
# Add these two variables in Render -> Environment:
# RAZORPAY_KEY_ID
# RAZORPAY_KEY_SECRET
#
# Never hard-code the secret key in this file or commit it to GitHub.

def _clean_env_value(value):
    """Clean a secret loaded from .env/environment without logging it."""
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'").strip()


RAZORPAY_KEY_ID = _clean_env_value(
    os.getenv("RAZORPAY_KEY_ID")
)
RAZORPAY_KEY_SECRET = _clean_env_value(
    os.getenv("RAZORPAY_KEY_SECRET")
)

razorpay_client = None

if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET:
    try:
        razorpay_client = razorpay.Client(
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
        )
        print("==========================================")
        print("RAZORPAY CONFIGURED")
        print("Key ID loaded: YES")
        print("Key ID prefix:", RAZORPAY_KEY_ID[:8])
        print("Secret loaded: YES")
        print("==========================================")
    except Exception as error:
        razorpay_client = None
        print("==========================================")
        print("RAZORPAY CLIENT INITIALIZATION FAILED")
        print("Error type:", type(error).__name__)
        print("Error:", repr(error))
        print("==========================================")
else:
    print("==========================================")
    print("RAZORPAY NOT CONFIGURED")
    print("Key ID loaded:", bool(RAZORPAY_KEY_ID))
    print("Secret loaded:", bool(RAZORPAY_KEY_SECRET))
    print("Set RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")
    print("==========================================")

# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):
    __tablename__ = "user"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    name = db.Column(
        db.String(150),
        nullable=False,
    )

    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    mobile = db.Column(db.String(20), nullable=True, unique=True)
    mobile_verified = db.Column(db.Boolean, default=False, nullable=False)

    email = db.Column(
        db.String(150),
        unique=True,
        nullable=False,
    )

    password = db.Column(
        db.String(255),
        nullable=False,
    )

    role = db.Column(
        db.String(30),
        default="student",
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )

    enrollments = db.relationship(
        "Enrollment",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    payments = db.relationship(
        "Payment",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    chat_messages = db.relationship(
        "ChatMessage",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )

    chatbot_leads = db.relationship(
        "ChatbotLead",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )


class SiteSetting(db.Model):
    """Simple key/value settings controlled by administrators."""

    __tablename__ = "site_settings"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    setting_key = db.Column(
        db.String(100),
        unique=True,
        nullable=False,
    )

    setting_value = db.Column(
        db.Text,
        nullable=True,
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class Course(db.Model):
    __tablename__ = "course"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    title = db.Column(
        db.String(200),
        nullable=False,
    )

    description = db.Column(
        db.Text,
        nullable=False,
    )

    price = db.Column(
        db.Float,
        default=0,
    )

    image = db.Column(
        db.String(300),
        nullable=True,
    )

    level = db.Column(
        db.String(50),
        default="Beginner",
    )

    duration = db.Column(
        db.String(100),
        default="8 Weeks",
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )

    enrollments = db.relationship(
        "Enrollment",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
    )

    payments = db.relationship(
        "Payment",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
    )

    videos = db.relationship(
        "CourseVideo",
        backref="course",
        lazy=True,
        cascade="all, delete-orphan",
    )


class CourseVideo(db.Model):
    __tablename__ = "course_video"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    title = db.Column(
        db.String(250),
        nullable=False,
    )

    video_url = db.Column(
        db.String(1000),
        nullable=True,
    )

    video_file = db.Column(
        db.String(500),
        nullable=True,
    )

    description = db.Column(
        db.Text,
        nullable=True,
    )

    duration = db.Column(
        db.String(100),
        nullable=True,
    )

    sort_order = db.Column(
        db.Integer,
        default=0,
    )

    is_active = db.Column(
        db.Boolean,
        default=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )


class CourseVideoProgress(db.Model):
    """Stores which individual course videos a student has completed."""

    __tablename__ = "course_video_progress"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    video_id = db.Column(
        db.Integer,
        db.ForeignKey("course_video.id"),
        nullable=False,
    )

    watched_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class ContactMessage(db.Model):
    __tablename__ = "contact_message"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    name = db.Column(
        db.String(150),
        nullable=False,
    )

    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    mobile = db.Column(db.String(20), nullable=True, unique=True)
    mobile_verified = db.Column(db.Boolean, default=False, nullable=False)

    email = db.Column(
        db.String(150),
        nullable=False,
    )

    subject = db.Column(
        db.String(250),
        nullable=False,
    )

    message = db.Column(
        db.Text,
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )

    is_read = db.Column(
        db.Boolean,
        default=False,
    )


class Enrollment(db.Model):
    __tablename__ = "enrollment"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    progress = db.Column(
        db.Integer,
        default=0,
    )

    enrolled_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )

    completed = db.Column(
        db.Boolean,
        default=False,
    )


class Payment(db.Model):
    __tablename__ = "payment"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
    )

    course_id = db.Column(
        db.Integer,
        db.ForeignKey("course.id"),
        nullable=False,
    )

    razorpay_order_id = db.Column(
        db.String(200),
        nullable=False,
    )

    razorpay_payment_id = db.Column(
        db.String(200),
        nullable=True,
    )

    razorpay_signature = db.Column(
        db.String(500),
        nullable=True,
    )

    amount = db.Column(
        db.Float,
        nullable=False,
    )

    currency = db.Column(
        db.String(10),
        default="INR",
    )

    status = db.Column(
        db.String(30),
        default="created",
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )

    paid_at = db.Column(
        db.DateTime,
        nullable=True,
    )


# ============================================================
# AI CHATBOT MODELS
# IMPORTANT: ChatMessage is defined ONLY ONCE.
# ============================================================

class ChatMessage(db.Model):
    __tablename__ = "chat_messages"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
    )

    question = db.Column(
        db.Text,
        nullable=False,
    )

    answer = db.Column(
        db.Text,
        nullable=False,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )


class ChatbotLead(db.Model):
    __tablename__ = "chatbot_leads"

    id = db.Column(
        db.Integer,
        primary_key=True,
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True,
    )

    name = db.Column(
        db.String(150),
        nullable=False,
    )

    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    mobile = db.Column(db.String(20), nullable=True, unique=True)
    mobile_verified = db.Column(db.Boolean, default=False, nullable=False)

    email = db.Column(
        db.String(150),
        nullable=False,
    )

    mobile = db.Column(
        db.String(30),
        nullable=False,
    )

    help_topic = db.Column(
        db.String(150),
        nullable=True,
    )

    experience = db.Column(
        db.String(100),
        nullable=True,
    )

    goal = db.Column(
        db.String(150),
        nullable=True,
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
    )


# ============================================================
# DATABASE HELPERS
# ============================================================

def add_missing_column(
        table_name,
        column_name,
        column_type,
        default_value=None,
):
    """
    Adds a missing column to an existing SQLite database.

    Note:
    This is a lightweight migration helper. It does not change
    existing column types or constraints.
    """

    inspector = inspect(db.engine)
    tables = inspector.get_table_names()

    if table_name not in tables:
        return

    existing_columns = {
        column["name"]
        for column in inspector.get_columns(table_name)
    }

    if column_name in existing_columns:
        return

    sql = (
        f"ALTER TABLE {table_name} "
        f"ADD COLUMN {column_name} {column_type}"
    )

    if default_value is not None:
        if isinstance(default_value, str):
            safe_value = default_value.replace("'", "''")
            sql += f" DEFAULT '{safe_value}'"
        else:
            sql += f" DEFAULT {default_value}"

    with db.engine.begin() as connection:
        connection.execute(text(sql))

    print(
        f"Added missing column: "
        f"{table_name}.{column_name}"
    )


def ensure_table(model):
    inspector = inspect(db.engine)

    if model.__tablename__ not in inspector.get_table_names():
        model.__table__.create(
            bind=db.engine,
            checkfirst=True,
        )


def migrate_database():
    """
    Creates missing tables and adds missing columns.

    This keeps the lightweight migration behavior from the
    original application while also including chatbot tables.
    """


with app.app_context():

    db.create_all()

    # ----------------------------------------------------
    # SITE SETTINGS
    # ----------------------------------------------------

    ensure_table(SiteSetting)

    # ----------------------------------------------------
    # USER
    # ----------------------------------------------------

    add_missing_column(
        "user",
        "name",
        "VARCHAR(150)",
        "",
    )

    add_missing_column(
        "user",
        "email",
        "VARCHAR(150)",
    )

    add_missing_column(
        "user",
        "password",
        "VARCHAR(255)",
    )

    add_missing_column(
        "user",
        "role",
        "VARCHAR(30)",
        "student",
    )

    add_missing_column(
        "user",
        "created_at",
        "DATETIME",
    )

    add_missing_column("user", "first_name", "VARCHAR(80)")
    add_missing_column("user", "last_name", "VARCHAR(80)")
    add_missing_column("user", "mobile", "VARCHAR(20)")
    add_missing_column("user", "mobile_verified", "BOOLEAN", "0")

    # ----------------------------------------------------
    # COURSE
    # ----------------------------------------------------

    add_missing_column(
        "course",
        "title",
        "VARCHAR(200)",
    )

    add_missing_column(
        "course",
        "description",
        "TEXT",
    )

    add_missing_column(
        "course",
        "price",
        "FLOAT",
        0,
    )

    add_missing_column(
        "course",
        "image",
        "VARCHAR(300)",
    )

    add_missing_column(
        "course",
        "level",
        "VARCHAR(50)",
        "Beginner",
    )

    add_missing_column(
        "course",
        "duration",
        "VARCHAR(100)",
        "8 Weeks",
    )

    add_missing_column(
        "course",
        "is_active",
        "BOOLEAN",
        1,
    )

    add_missing_column(
        "course",
        "created_at",
        "DATETIME",
    )

    # ----------------------------------------------------
    # CONTACT MESSAGE
    # ----------------------------------------------------

    ensure_table(ContactMessage)

    add_missing_column(
        "contact_message",
        "name",
        "VARCHAR(150)",
        "",
    )

    add_missing_column(
        "contact_message",
        "email",
        "VARCHAR(150)",
        "",
    )

    add_missing_column(
        "contact_message",
        "subject",
        "VARCHAR(250)",
        "",
    )

    add_missing_column(
        "contact_message",
        "message",
        "TEXT",
        "",
    )

    add_missing_column(
        "contact_message",
        "created_at",
        "DATETIME",
    )

    add_missing_column(
        "contact_message",
        "is_read",
        "BOOLEAN",
        0,
    )

    # ----------------------------------------------------
    # ENROLLMENT
    # ----------------------------------------------------

    ensure_table(Enrollment)

    add_missing_column(
        "enrollment",
        "user_id",
        "INTEGER",
    )

    add_missing_column(
        "enrollment",
        "course_id",
        "INTEGER",
    )

    add_missing_column(
        "enrollment",
        "progress",
        "INTEGER",
        0,
    )

    add_missing_column(
        "enrollment",
        "enrolled_at",
        "DATETIME",
    )

    add_missing_column(
        "enrollment",
        "completed",
        "BOOLEAN",
        0,
    )

    # ----------------------------------------------------
    # PAYMENT
    # ----------------------------------------------------

    ensure_table(Payment)

    add_missing_column(
        "payment",
        "user_id",
        "INTEGER",
    )

    add_missing_column(
        "payment",
        "course_id",
        "INTEGER",
    )

    add_missing_column(
        "payment",
        "razorpay_order_id",
        "VARCHAR(200)",
    )

    add_missing_column(
        "payment",
        "razorpay_payment_id",
        "VARCHAR(200)",
    )

    add_missing_column(
        "payment",
        "razorpay_signature",
        "VARCHAR(500)",
    )

    add_missing_column(
        "payment",
        "amount",
        "FLOAT",
        0,
    )

    add_missing_column(
        "payment",
        "currency",
        "VARCHAR(10)",
        "INR",
    )

    add_missing_column(
        "payment",
        "status",
        "VARCHAR(30)",
        "created",
    )

    add_missing_column(
        "payment",
        "created_at",
        "DATETIME",
    )

    add_missing_column(
        "payment",
        "paid_at",
        "DATETIME",
    )

    # ----------------------------------------------------
    # COURSE VIDEO
    # ----------------------------------------------------

    ensure_table(CourseVideo)

    add_missing_column(
        "course_video",
        "course_id",
        "INTEGER",
    )

    add_missing_column(
        "course_video",
        "title",
        "VARCHAR(250)",
        "",
    )

    add_missing_column(
        "course_video",
        "video_url",
        "VARCHAR(1000)",
    )

    add_missing_column(
        "course_video",
        "video_file",
        "VARCHAR(500)",
    )

    add_missing_column(
        "course_video",
        "description",
        "TEXT",
    )

    add_missing_column(
        "course_video",
        "duration",
        "VARCHAR(100)",
    )

    add_missing_column(
        "course_video",
        "sort_order",
        "INTEGER",
        0,
    )

    add_missing_column(
        "course_video",
        "is_active",
        "BOOLEAN",
        1,
    )

    add_missing_column(
        "course_video",
        "created_at",
        "DATETIME",
    )

    # ----------------------------------------------------
    # REPAIR OLD VIDEO RECORDS
    # ----------------------------------------------------
    # Older databases can contain NULL in is_active.
    # Treat those existing videos as active so they are
    # visible to enrolled students. Explicit False remains hidden.
    try:
        db.session.execute(
            text(
                "UPDATE course_video "
                "SET is_active = 1 "
                "WHERE is_active IS NULL"
            )
        )
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Course video repair error:", error)

    # ----------------------------------------------------
    # COURSE VIDEO PROGRESS
    # ----------------------------------------------------
    # Stores per-student lesson completion independently from
    # the aggregate Enrollment.progress field.
    ensure_table(CourseVideoProgress)

    add_missing_column(
        "course_video_progress",
        "user_id",
        "INTEGER",
    )
    add_missing_column(
        "course_video_progress",
        "course_id",
        "INTEGER",
    )
    add_missing_column(
        "course_video_progress",
        "video_id",
        "INTEGER",
    )
    add_missing_column(
        "course_video_progress",
        "watched_at",
        "DATETIME",
    )

    # CHAT MESSAGE
    # ----------------------------------------------------

    ensure_table(ChatMessage)

    add_missing_column(
        "chat_messages",
        "user_id",
        "INTEGER",
    )

    add_missing_column(
        "chat_messages",
        "question",
        "TEXT",
        "",
    )

    add_missing_column(
        "chat_messages",
        "answer",
        "TEXT",
        "",
    )

    add_missing_column(
        "chat_messages",
        "created_at",
        "DATETIME",
    )

    # ----------------------------------------------------
    # CHATBOT LEAD
    # ----------------------------------------------------

    ensure_table(ChatbotLead)

    add_missing_column(
        "chatbot_leads",
        "user_id",
        "INTEGER",
    )

    add_missing_column(
        "chatbot_leads",
        "name",
        "VARCHAR(150)",
        "",
    )

    add_missing_column(
        "chatbot_leads",
        "email",
        "VARCHAR(150)",
        "",
    )

    add_missing_column(
        "chatbot_leads",
        "mobile",
        "VARCHAR(30)",
        "",
    )

    add_missing_column(
        "chatbot_leads",
        "help_topic",
        "VARCHAR(150)",
    )

    add_missing_column(
        "chatbot_leads",
        "experience",
        "VARCHAR(100)",
    )

    add_missing_column(
        "chatbot_leads",
        "goal",
        "VARCHAR(150)",
    )

    add_missing_column(
        "chatbot_leads",
        "created_at",
        "DATETIME",
    )

    print("Database migration completed.")


# ============================================================
# LOGIN REQUIRED
# ============================================================

def login_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please login to continue.",
                "warning",
            )

            return redirect(
                url_for(
                    "login",
                    next=request.path,
                )
            )

        return function(*args, **kwargs)

    return decorated_function


# ============================================================
# ADMIN REQUIRED
# ============================================================

def admin_required(function):

    @wraps(function)
    def decorated_function(*args, **kwargs):

        if not session.get("user_id"):

            flash(
                "Please login as administrator.",
                "warning",
            )

            return redirect(url_for("login"))

        if session.get("role") != "admin":

            flash(
                "Administrator access required.",
                "danger",
            )

            return redirect(
                url_for("student_dashboard")
            )

        return function(*args, **kwargs)

    return decorated_function


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def allowed_video_file(filename):
    return (
            bool(filename)
            and "." in filename
            and filename.rsplit(".", 1)[1].lower()
            in ALLOWED_VIDEO_EXTENSIONS
    )


def allowed_image_file(filename):
    return (
            bool(filename)
            and "." in filename
            and filename.rsplit(".", 1)[1].lower()
            in ALLOWED_IMAGE_EXTENSIONS
    )


def save_uploaded_image(file_storage, prefix):
    """Save a JPG/PNG/WEBP upload with a unique safe filename."""

    if not file_storage or not file_storage.filename:
        return None

    original_name = secure_filename(file_storage.filename)

    if not allowed_image_file(original_name):
        raise ValueError(
            "Invalid image format. Use JPG, JPEG, PNG or WEBP."
        )

    extension = original_name.rsplit(".", 1)[1].lower()
    unique_name = (
        f"{prefix}_{uuid4().hex}.{extension}"
    )

    destination = os.path.join(
        app.config["STATIC_UPLOAD_FOLDER"],
        unique_name,
    )

    file_storage.save(destination)
    return unique_name


def remove_uploaded_image(filename):
    """Remove an uploaded image if it exists in static/uploads."""

    if not filename:
        return

    safe_name = os.path.basename(filename)
    path = os.path.join(
        app.config["STATIC_UPLOAD_FOLDER"],
        safe_name,
    )

    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError as error:
            print("Could not delete image file:", error)


def get_site_setting(key, default=""):
    setting = SiteSetting.query.filter_by(
        setting_key=key
    ).first()

    if setting and setting.setting_value is not None:
        return setting.setting_value

    return default


def get_video_source(video):
    if video.video_file:
        return url_for(
            "uploaded_video",
            filename=video.video_file,
        )

    return video.video_url


def get_clean_mobile(mobile):
    return (
        mobile
        .replace(" ", "")
        .replace("-", "")
        .replace("+", "")
        .replace("(", "")
        .replace(")", "")
    )


# Make helper available to templates if needed.
app.jinja_env.globals["get_video_source"] = get_video_source


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    courses = (
        Course.query
        .filter_by(is_active=True)
        .order_by(Course.id.desc())
        .limit(6)
        .all()
    )

    return render_template(
        "index.html",
        courses=courses,
    )


# ============================================================
# ABOUT
# ============================================================

@app.route("/about")
def about():
    return render_template("about.html")
#extra
@app.route("/chatbot-emulator")
def chatbot_emulator():
    return render_template("chatbot.html")
@app.route("/chatbot-ui")
def chatbot_ui():
    return render_template("chatbot.html")
# ============================================================
# LOCAL NIKSS AI CHATBOT KNOWLEDGE BASE
# No API key required
# ============================================================

CHATBOT_KNOWLEDGE = [
    {
        "keywords": ["hello", "hi", "hey", "namaste", "good morning", "good evening"],
        "answer": """
        <b>Hello! 👋</b><br><br>
        I'm <b>NIKSS AI Assistant</b>, your coding guide.<br><br>
        I can help you with Java, Python, Spring Boot, DSA, SQL,
        HTML/CSS, Flask, debugging, projects and interview preparation.
        <br><br>How can I help you today?
        """
    },
    {
        "keywords": ["what is java", "java language", "java programming", "java"],
        "answer": """
        <b>Java ☕</b><br><br>
        Java is a high-level, object-oriented programming language.
        It is widely used for backend, enterprise, web and Android development.
        <br><br><b>Key Features:</b><br>
        • Object-Oriented<br>
        • Platform Independent<br>
        • Secure<br>
        • Robust<br>
        • Multithreaded
        """
    },
    {
        "keywords": ["what is python", "python language", "python programming", "python"],
        "answer": """
        <b>Python 🐍</b><br><br>
        Python is a high-level, interpreted programming language known
        for its simple and readable syntax.<br><br>
        <b>Common uses:</b><br>
        • Web Development<br>• AI/ML<br>• Data Science<br>• Automation<br>• Scripting
        """
    },
    {
        "keywords": ["what is spring boot", "spring boot framework", "spring boot"],
        "answer": """
        <b>Spring Boot 🌱</b><br><br>
        Spring Boot is a Java framework used to build production-ready
        applications quickly.<br><br>
        <b>Common uses:</b><br>
        • REST APIs<br>• Backend Applications<br>• Microservices<br>• Enterprise Applications
        """
    },
    {
        "keywords": ["what is dsa", "data structures and algorithms", "data structure", "dsa"],
        "answer": """
        <b>DSA 🧠</b><br><br>
        DSA means <b>Data Structures and Algorithms</b>.<br><br>
        Important topics include:<br>
        • Arrays<br>• Linked Lists<br>• Stack<br>• Queue<br>• Trees<br>
        • Graphs<br>• Searching<br>• Sorting<br>• Recursion
        """
    },
    {
        "keywords": ["what is sql", "sql language", "sql database", "sql"],
        "answer": """
        <b>SQL 🗄️</b><br><br>
        SQL stands for <b>Structured Query Language</b>.
        It is used to store, retrieve and manage data in relational databases.
        <br><br><b>Common commands:</b><br>
        SELECT • INSERT • UPDATE • DELETE
        """
    },
    {
        "keywords": ["what is html", "html"],
        "answer": """
        <b>HTML 🌐</b><br><br>
        HTML stands for <b>HyperText Markup Language</b>.
        It provides the structure of web pages using headings, paragraphs,
        links, forms, images and other elements.
        """
    },
    {
        "keywords": ["what is css", "css"],
        "answer": """
        <b>CSS 🎨</b><br><br>
        CSS stands for <b>Cascading Style Sheets</b>.
        It controls the appearance, layout, spacing, colors, animations
        and responsive design of web pages.
        """
    },
    {
        "keywords": ["what is flask", "flask framework", "flask"],
        "answer": """
        <b>Flask 🐍</b><br><br>
        Flask is a lightweight Python web framework used to create
        web applications and REST APIs.<br><br>
        A Flask application commonly uses routes, templates, request handling,
        sessions and database integration.
        """
    },
    {
        "keywords": ["what is oop", "what is oops", "object oriented programming", "oops"],
        "answer": """
        <b>OOP - Object-Oriented Programming</b><br><br>
        The four major concepts are:<br>
        1. <b>Encapsulation</b><br>
        2. <b>Inheritance</b><br>
        3. <b>Polymorphism</b><br>
        4. <b>Abstraction</b>
        """
    },
    {
        "keywords": ["what is inheritance", "inheritance"],
        "answer": """
        <b>Inheritance</b><br><br>
        Inheritance allows a child class to acquire properties and methods
        from a parent class. It promotes code reuse and supports relationships
        between classes.
        """
    },
    {
        "keywords": ["what is polymorphism", "polymorphism"],
        "answer": """
        <b>Polymorphism</b><br><br>
        Polymorphism means <b>many forms</b>. It allows the same method or
        interface to behave differently depending on the object.
        """
    },
    {
        "keywords": ["what is encapsulation", "encapsulation"],
        "answer": """
        <b>Encapsulation</b><br><br>
        Encapsulation means combining data and methods inside a class and
        controlling how that data is accessed.
        """
    },
    {
        "keywords": ["what is abstraction", "abstraction"],
        "answer": """
        <b>Abstraction</b><br><br>
        Abstraction hides unnecessary implementation details and exposes
        only the functionality required by the user.
        """
    },
    {
        "keywords": ["what is api", "application programming interface", "api"],
        "answer": """
        <b>API 🔗</b><br><br>
        API stands for <b>Application Programming Interface</b>.
        It allows different software components to communicate.<br><br>
        REST APIs commonly use GET, POST, PUT, PATCH and DELETE.
        """
    },
    {
        "keywords": ["what is rest api", "rest api"],
        "answer": """
        <b>REST API</b><br><br>
        A REST API exposes resources through HTTP endpoints.
        Common HTTP methods are GET, POST, PUT/PATCH and DELETE.
        """
    },
    {
        "keywords": ["what is json", "json"],
        "answer": """
        <b>JSON</b><br><br>
        JSON stands for <b>JavaScript Object Notation</b>.
        It is a lightweight format commonly used to exchange data between
        frontend and backend applications.
        """
    },
    {
        "keywords": ["what is git", "git version control", "git"],
        "answer": """
        <b>Git</b><br><br>
        Git is a distributed version-control system used to track code changes,
        create branches and collaborate on software projects.
        """
    },
    {
        "keywords": ["what is github", "github"],
        "answer": """
        <b>GitHub</b><br><br>
        GitHub is a platform for hosting Git repositories and collaborating
        on software projects through commits, branches and pull requests.
        """
    },
    {
        "keywords": ["debug", "debugging", "debug my code", "error in code"],
        "answer": """
        <b>How to Debug Code 🐞</b><br><br>
        1. Read the complete error message.<br>
        2. Find the line causing the error.<br>
        3. Check variable values and inputs.<br>
        4. Use breakpoints or logging.<br>
        5. Test a smaller part of the program.<br>
        6. Fix the root cause.<br>
        7. Run the program and tests again.
        """
    },
    {
        "keywords": ["java interview questions", "java interview"],
        "answer": """
        <b>Java Interview Questions ☕</b><br><br>
        1. What is Java?<br>
        2. What are JVM, JRE and JDK?<br>
        3. Explain OOP concepts.<br>
        4. What is inheritance?<br>
        5. What is polymorphism?<br>
        6. Explain exception handling.<br>
        7. What are Java Collections?<br>
        8. What is multithreading?<br>
        9. What is an interface?<br>
        10. What is Spring Boot?
        """
    },
    {
        "keywords": ["python interview questions", "python interview"],
        "answer": """
        <b>Python Interview Questions 🐍</b><br><br>
        1. What is Python?<br>
        2. List vs Tuple?<br>
        3. What is a Dictionary?<br>
        4. What is a Function?<br>
        5. What is Inheritance?<br>
        6. Explain Polymorphism.<br>
        7. What is Exception Handling?<br>
        8. What is Lambda?<br>
        9. What are Decorators?<br>
        10. What is a Virtual Environment?
        """
    },
    {
        "keywords": ["project idea", "project ideas", "projects", "project"],
        "answer": """
        <b>Project Ideas 🚀</b><br><br>
        • E-Commerce Backend<br>
        • Student Management System<br>
        • Online Learning Platform<br>
        • AI Coding Tutor<br>
        • Expense Tracker<br>
        • Job Portal<br>
        • Library Management System<br>
        • REST API Project
        """
    },
    {
        "keywords": ["course", "courses", "learning"],
        "answer": """
        <b>NIKSS Coding Hub Courses 📚</b><br><br>
        You can use the Courses section of NIKSS Coding Hub to explore
        available programming courses. The platform supports course access,
        enrollment and learning resources.
        """
    },
    {
        "keywords": ["fee", "fees", "price", "cost"],
        "answer": """
        <b>Course Fees 💳</b><br><br>
        Course prices can vary by course. Please open the Courses section
        of NIKSS Coding Hub to see the current price of the course you want.
        """
    },
    {
        "keywords": ["enroll", "enrollment", "join course"],
        "answer": """
        <b>Course Enrollment 🎓</b><br><br>
        To enroll, open a course, review its details and follow the enrollment
        and payment steps provided by NIKSS Coding Hub.
        """
    },
    {
        "keywords": ["nikss coding hub", "nikss"],
        "answer": """
        <b>NIKSS Coding Hub 🚀</b><br><br>
        NIKSS Coding Hub is an educational platform designed to help students
        learn programming, access courses, practice coding and prepare for
        technical interviews.
        """
    },
    {
        "keywords": ["help", "what can you do", "how can you help"],
        "answer": """
        <b>I can help you with 👨‍💻</b><br><br>
        ☕ Java<br>
        🐍 Python<br>
        🌱 Spring Boot<br>
        🧠 DSA<br>
        🗄️ SQL<br>
        🌐 HTML/CSS<br>
        🐞 Debugging<br>
        🎯 Interview Preparation<br>
        🚀 Projects<br>
        🔧 Flask & REST APIs
        """
    },
]


def get_local_chatbot_answer(question):
    """Return a predefined answer without using an external API."""
    normalized_question = " ".join(question.lower().strip().split())
    matches = []

    for item in CHATBOT_KNOWLEDGE:
        score = 0
        for keyword in item["keywords"]:
            if keyword in normalized_question:
                score = max(score, len(keyword))

        if score > 0:
            matches.append((score, item["answer"].strip()))

    if matches:
        # Longest matching keyword wins, so specific questions beat generic ones.
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    return """
    <b>I'm still learning 🤖</b><br><br>
    I don't have a predefined answer for that question yet.<br><br>
    Try asking about <b>Java, Python, DSA, Spring Boot, SQL,
    HTML/CSS, Flask, debugging, projects or interview questions.</b>
    <br><br>
    <small>This version works without an external API key.</small>
    """.strip()


# ============================================================
# CHATBOT PAGE
# ============================================================

@app.route("/chatbot", methods=["GET"])
@login_required
def chatbot():
    return render_template("chatbot.html")


# ============================================================
# CHATBOT - NORMAL MESSAGE
# ============================================================

@app.route("/chatbot", methods=["POST"])
@login_required
def chatbot_message():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "answer": "Invalid request.",
        }), 400

    question = str(
        data.get("question", "")
    ).strip()

    if not question:
        return jsonify({
            "success": False,
            "answer": "Please enter a question.",
        }), 400

    # --------------------------------------------------------
    # LOCAL CHATBOT RESPONSE
    # No API key is required.
    # --------------------------------------------------------

    answer = get_local_chatbot_answer(question)

    # --------------------------------------------------------
    # SAVE CHAT
    # --------------------------------------------------------

    chat = ChatMessage(
        user_id=session.get("user_id"),
        question=question,
        answer=answer,
    )

    try:
        db.session.add(chat)
        db.session.commit()

    except Exception as error:
        db.session.rollback()
        print("Chat save error:", error)

        return jsonify({
            "success": False,
            "answer": "Unable to save the chat message.",
        }), 500

    return jsonify({
        "success": True,
        "answer": answer,
    })


# ============================================================
# CHATBOT - SAVE VISITOR INFORMATION
# ============================================================

@app.route(
    "/chatbot/intake",
    methods=["POST"],
)
@login_required
def chatbot_intake():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid request.",
        }), 400

    name = str(
        data.get("name", "")
    ).strip()

    email = str(
        data.get("email", "")
    ).strip().lower()

    mobile = str(
        data.get("mobile", "")
    ).strip()

    help_topic = str(
        data.get("help_topic", "")
    ).strip()

    experience = str(
        data.get("experience", "")
    ).strip()

    goal = str(
        data.get("goal", "")
    ).strip()

    if not name:
        return jsonify({
            "success": False,
            "message": "Please enter your name.",
        }), 400

    if not email:
        return jsonify({
            "success": False,
            "message": "Please enter your email.",
        }), 400

    if not mobile:
        return jsonify({
            "success": False,
            "message": "Please enter your mobile number.",
        }), 400

    if "@" not in email or "." not in email:
        return jsonify({
            "success": False,
            "message": "Please enter a valid email address.",
        }), 400

    clean_mobile = get_clean_mobile(mobile)

    if not clean_mobile.isdigit():
        return jsonify({
            "success": False,
            "message": "Please enter a valid mobile number.",
        }), 400

    if len(clean_mobile) < 10:
        return jsonify({
            "success": False,
            "message": (
                "Mobile number must contain at least 10 digits."
            ),
        }), 400

    lead = ChatbotLead(
        user_id=session.get("user_id"),
        name=name,
        email=email,
        mobile=mobile,
        help_topic=help_topic,
        experience=experience,
        goal=goal,
    )

    try:
        db.session.add(lead)
        db.session.commit()

    except Exception as error:
        db.session.rollback()
        print("Chatbot lead save error:", error)

        return jsonify({
            "success": False,
            "message": "Unable to save your information.",
        }), 500

    return jsonify({
        "success": True,
        "message": (
            f"Thank you, {name}! "
            "Your information has been received. "
            "How can I help you today?"
        ),
    })


# ============================================================
# CONTACT
# ============================================================

@app.route(
    "/contact",
    methods=["GET", "POST"],
)
def contact():

    if request.method == "POST":

        name = request.form.get(
            "name",
            "",
        ).strip()

        email = request.form.get(
            "email",
            "",
        ).strip().lower()

        subject = request.form.get(
            "subject",
            "",
        ).strip()

        message = request.form.get(
            "message",
            "",
        ).strip()

        if not name or not email or not subject or not message:

            flash(
                "Please fill all fields.",
                "error",
            )

            return redirect(
                url_for("contact")
            )

        if "@" not in email:

            flash(
                "Please enter a valid email address.",
                "error",
            )

            return redirect(
                url_for("contact")
            )

        new_message = ContactMessage(
            name=name,
            email=email,
            subject=subject,
            message=message,
        )

        try:
            db.session.add(new_message)
            db.session.commit()

        except Exception as error:
            db.session.rollback()
            print("Contact message error:", error)

            flash(
                "Unable to send your message.",
                "error",
            )

            return redirect(
                url_for("contact")
            )

        flash(
            "Message sent successfully!",
            "success",
        )

        return redirect(
            url_for("contact")
        )

    return render_template("contact.html")


# ============================================================
# COURSES
# ============================================================

@app.route("/courses")
def courses():

    courses_list = (
        Course.query
        .filter_by(is_active=True)
        .order_by(Course.id.asc())
        .all()
    )

    return render_template(
        "courses.html",
        courses=courses_list,
    )


# ============================================================
# COURSE DETAILS
# ============================================================

@app.route("/course/<int:course_id>")
def course_details(course_id):

    course = Course.query.get_or_404(course_id)

    enrolled = False

    if session.get("user_id"):

        existing_enrollment = (
            Enrollment.query
            .filter_by(
                user_id=session["user_id"],
                course_id=course.id,
            )
            .first()
        )

        enrolled = existing_enrollment is not None

    return render_template(
        "course_details.html",
        course=course,
        enrolled=enrolled,
    )

# ============================================================
# REGISTER
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():
    """Google-only account creation. New accounts are created directly after Google authentication."""
    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("student_dashboard"))
    return redirect(url_for("google_login"))


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"],
)
def login():
    """
    Google-only authentication for students.

    Password/email login is intentionally disabled so users cannot
    sign in or create accounts without completing Google authentication.
    """
    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("student_dashboard"))

    if request.method == "POST":
        flash(
            "Email/password login is disabled. Please continue with Google.",
            "warning",
        )
        return redirect(url_for("login"))

    return render_template("login.html")


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route("/login/google")
def google_login():

    if session.get("user_id"):
        if session.get("role") == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("student_dashboard"))

    if google is None:
        flash(
            "Google login is not configured on the server.",
            "danger",
        )
        return redirect(url_for("login"))

    try:
        redirect_uri = url_for(
            "google_callback",
            _external=True,
        )
        return google.authorize_redirect(redirect_uri)
    except Exception as error:
        print("Google authorization error:", repr(error))
        flash(
            "Unable to start Google login. Please try again.",
            "danger",
        )
        return redirect(url_for("login"))


@app.route("/login/google/callback")
def google_callback():

    if google is None:
        flash("Google login is not configured on the server.", "danger")
        return redirect(url_for("login"))

    try:
        token = google.authorize_access_token()
        user_info = token.get("userinfo")

        if not user_info:
            user_info = google.userinfo()

        email = str(user_info.get("email") or "").strip().lower()
        name = str(user_info.get("name") or "").strip()
        email_verified = user_info.get("email_verified")

        if not email:
            raise RuntimeError("Google did not return an email address.")

        if email_verified is not True:
            raise RuntimeError("Google email verification was not confirmed.")

        if not name:
            name = email.split("@", 1)[0]

        user = User.query.filter_by(email=email).first()

        # The three configured Google accounts are always administrators.
        if email in ADMIN_GOOGLE_EMAILS:
            if user is None:
                user = User(
                    name=name,
                    first_name=name.split(" ", 1)[0] if name else None,
                    last_name=name.split(" ", 1)[1] if " " in name else None,
                    email=email,
                    password=generate_password_hash(uuid4().hex + uuid4().hex),
                    role="admin",
                )
                db.session.add(user)
            else:
                user.role = "admin"
                user.name = name or user.name
                if not user.first_name and name:
                    user.first_name = name.split(" ", 1)[0]
                if not user.last_name and " " in name:
                    user.last_name = name.split(" ", 1)[1]

            db.session.commit()

            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name
            session["user_email"] = user.email
            session["role"] = "admin"
            session["auth_provider"] = "google_admin"

            flash(f"Welcome Admin, {user.name}!", "success")
            return redirect(url_for("admin_dashboard"))

        # Every other verified Google account becomes a student immediately.
        # No mobile number, OTP, Twilio, or second registration step is required.
        if user is None:
            first_name = name.split(" ", 1)[0] if name else email.split("@", 1)[0]
            last_name = name.split(" ", 1)[1] if " " in name else ""
            user = User(
                name=name,
                first_name=first_name,
                last_name=last_name or None,
                mobile=None,
                mobile_verified=False,
                email=email,
                password=generate_password_hash(uuid4().hex + uuid4().hex),
                role="student",
            )
            db.session.add(user)
        else:
            user.role = "student"
            user.name = name or user.name
            if not user.first_name and name:
                user.first_name = name.split(" ", 1)[0]
            if not user.last_name and " " in name:
                user.last_name = name.split(" ", 1)[1]

        db.session.commit()

        session.clear()
        session["user_id"] = user.id
        session["user_name"] = user.name
        session["user_email"] = user.email
        session["role"] = "student"
        session["auth_provider"] = "google"

        flash(f"Welcome, {user.name}! Your account is ready.", "success")
        return redirect(url_for("student_dashboard"))

    except Exception as error:
        db.session.rollback()
        print("==========================================")
        print("GOOGLE LOGIN FAILED")
        print("Error type:", type(error).__name__)
        print("Error:", repr(error))
        print("==========================================")
        flash("Google login failed. Please try again.", "danger")
        return redirect(url_for("login"))


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out successfully.",
        "success",
    )

    return redirect(
        url_for("home")
    )


# ============================================================
# RAZORPAY - CREATE ORDER
# ============================================================

@app.route(
    "/payment/create/<int:course_id>",
    methods=["POST"],
)
@login_required
def create_payment_order(course_id):

    if session.get("role") == "admin":
        return jsonify({
            "success": False,
            "message": "Administrators cannot purchase courses.",
        }), 403

    course = Course.query.get_or_404(course_id)

    if not course.is_active:
        return jsonify({
            "success": False,
            "message": "This course is not active.",
        }), 400

    existing_enrollment = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course.id,
    ).first()

    if existing_enrollment:
        return jsonify({
            "success": False,
            "message": "You are already enrolled.",
        }), 400

    try:
        course_price = float(course.price or 0)
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "message": "Invalid course price configured by administrator.",
        }), 400

    if course_price < 0:
        return jsonify({
            "success": False,
            "message": "Course price cannot be negative.",
        }), 400

    # Free course: no Razorpay order is required.
    if course_price == 0:
        enrollment = Enrollment(
            user_id=session["user_id"],
            course_id=course.id,
            progress=0,
            completed=False,
        )

        try:
            db.session.add(enrollment)
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            print("Free enrollment error:", error)
            return jsonify({
                "success": False,
                "message": "Unable to enroll in the course.",
            }), 500

        return jsonify({
            "success": True,
            "free": True,
            "redirect_url": url_for("student_dashboard"),
        })

    # Paid course: Razorpay must be configured.
    if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET or razorpay_client is None:
        print("PAYMENT ERROR: Razorpay environment variables are missing.")
        return jsonify({
            "success": False,
            "message": (
                "Payment is temporarily unavailable because Razorpay "
                "is not configured on the server. Please contact the administrator."
            ),
        }), 503

    amount_paise = int(round(course_price * 100))

    if amount_paise < 100:
        return jsonify({
            "success": False,
            "message": "Course price must be at least ₹1.",
        }), 400

    receipt = (
        f"course_{course.id}_"
        f"user_{session['user_id']}_"
        f"{int(datetime.utcnow().timestamp())}_"
        f"{uuid4().hex[:8]}"
    )

    try:
        print("==========================================")
        print("CREATING RAZORPAY ORDER")
        print("Course ID:", course.id)
        print("Course price INR:", course_price)
        print("Amount paise:", amount_paise)
        print("Currency: INR")
        print("Key ID prefix:", RAZORPAY_KEY_ID[:8])
        print("==========================================")

        razorpay_order = razorpay_client.order.create({
            "amount": amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {
                "course_id": str(course.id),
                "course_title": str(course.title),
                "user_id": str(session["user_id"]),
                "user_email": session.get("user_email", ""),
            },
        })

        if not isinstance(razorpay_order, dict):
            raise RuntimeError(
                "Razorpay returned a non-object order response."
            )

        if not razorpay_order.get("id"):
            raise RuntimeError(
                "Razorpay returned an order response without an ID."
            )

        print("RAZORPAY ORDER CREATED")
        print("Order ID:", razorpay_order["id"])
        print("==========================================")

    except Exception as error:
        print("==========================================")
        print("RAZORPAY ORDER CREATION FAILED")
        print("Course ID:", course.id)
        print("User ID:", session.get("user_id"))
        print("Key ID loaded:", bool(RAZORPAY_KEY_ID))
        print("Secret loaded:", bool(RAZORPAY_KEY_SECRET))
        print("Key ID prefix:", RAZORPAY_KEY_ID[:8] if RAZORPAY_KEY_ID else "NONE")
        print("Error type:", type(error).__name__)
        print("Error:", repr(error))
        print("==========================================")

        return jsonify({
            "success": False,
            "message": (
                "Unable to create the Razorpay payment order. "
                "Check the terminal for the exact Razorpay error."
            ),
            "error_type": type(error).__name__,
        }), 502

    payment = Payment(
        user_id=session["user_id"],
        course_id=course.id,
        razorpay_order_id=razorpay_order["id"],
        amount=course_price,
        currency="INR",
        status="created",
    )

    try:
        db.session.add(payment)
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Payment record error:", repr(error))
        return jsonify({
            "success": False,
            "message": "Unable to save payment order.",
        }), 500

    return jsonify({
        "success": True,
        "free": False,
        "key": RAZORPAY_KEY_ID,
        "order_id": razorpay_order["id"],
        "amount": amount_paise,
        "currency": "INR",
        "course_id": course.id,
        "course_title": course.title,
        "user_name": session.get("user_name", ""),
        "user_email": session.get("user_email", ""),
    })



# ============================================================
# RAZORPAY - VERIFY PAYMENT
# ============================================================
# ============================================================
# RAZORPAY - VERIFY PAYMENT
# ============================================================

@app.route(
    "/payment/verify",
    methods=["POST"],
)
@app.route(
    "/payment/verify/<int:course_id>",
    methods=["POST"],
)
@login_required
def verify_payment(course_id=None):

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Invalid payment data.",
        }), 400

    # --------------------------------------------------------
    # GET RAZORPAY PAYMENT DETAILS
    # --------------------------------------------------------

    razorpay_order_id = str(
        data.get("razorpay_order_id", "")
    ).strip()

    razorpay_payment_id = str(
        data.get("razorpay_payment_id", "")
    ).strip()

    razorpay_signature = str(
        data.get("razorpay_signature", "")
    ).strip()

    # Course ID can come from JSON or from URL
    course_id = data.get("course_id", course_id)

    # --------------------------------------------------------
    # VALIDATE PAYMENT DATA
    # --------------------------------------------------------

    if not all([
        razorpay_order_id,
        razorpay_payment_id,
        razorpay_signature,
        course_id is not None,
    ]):
        return jsonify({
            "success": False,
            "message": "Payment verification information is incomplete.",
        }), 400

    try:
        course_id = int(course_id)

    except (ValueError, TypeError):

        return jsonify({
            "success": False,
            "message": "Invalid course ID.",
        }), 400

    # --------------------------------------------------------
    # FIND PAYMENT RECORD
    # --------------------------------------------------------

    payment = Payment.query.filter_by(
        razorpay_order_id=razorpay_order_id,
        user_id=session["user_id"],
        course_id=course_id,
    ).first()

    if not payment:

        print("==========================================")
        print("PAYMENT RECORD NOT FOUND")
        print("User ID:", session.get("user_id"))
        print("Course ID:", course_id)
        print("Order ID:", razorpay_order_id)
        print("==========================================")

        return jsonify({
            "success": False,
            "message": "Payment record not found.",
        }), 404

    # --------------------------------------------------------
    # ALREADY VERIFIED
    # --------------------------------------------------------

    if payment.status == "paid":

        return jsonify({
            "success": True,
            "message": "Payment already verified.",
            "redirect_url": url_for("student_dashboard"),
        })

    # --------------------------------------------------------
    # CHECK RAZORPAY CONFIGURATION
    # --------------------------------------------------------

    if (
            not RAZORPAY_KEY_ID
            or not RAZORPAY_KEY_SECRET
            or razorpay_client is None
    ):

        print("PAYMENT VERIFY ERROR: Razorpay is not configured.")

        return jsonify({
            "success": False,
            "message": "Razorpay is not configured on the server.",
        }), 503

    # --------------------------------------------------------
    # VERIFY RAZORPAY SIGNATURE
    # --------------------------------------------------------

    try:

        print("==========================================")
        print("VERIFYING RAZORPAY PAYMENT")
        print("Course ID:", course_id)
        print("Order ID:", razorpay_order_id)
        print("Payment ID:", razorpay_payment_id)
        print("==========================================")

        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

    except Exception as error:

        print("==========================================")
        print("RAZORPAY SIGNATURE VERIFICATION FAILED")
        print("Course ID:", course_id)
        print("Order ID:", razorpay_order_id)
        print("Payment ID:", razorpay_payment_id)
        print("Error Type:", type(error).__name__)
        print("Error:", repr(error))
        print("==========================================")

        payment.status = "failed"

        try:
            db.session.commit()

        except Exception:
            db.session.rollback()

        return jsonify({
            "success": False,
            "message": "Payment verification failed.",
        }), 400

    # --------------------------------------------------------
    # PAYMENT VERIFIED SUCCESSFULLY
    # --------------------------------------------------------

    payment.status = "paid"
    payment.razorpay_payment_id = razorpay_payment_id
    payment.razorpay_signature = razorpay_signature
    payment.paid_at = datetime.utcnow()

    # --------------------------------------------------------
    # CHECK EXISTING ENROLLMENT
    # --------------------------------------------------------

    existing_enrollment = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course_id,
    ).first()

    # --------------------------------------------------------
    # CREATE ENROLLMENT
    # --------------------------------------------------------

    if not existing_enrollment:

        enrollment = Enrollment(
            user_id=session["user_id"],
            course_id=course_id,
            progress=0,
            completed=False,
        )

        db.session.add(enrollment)

    # --------------------------------------------------------
    # SAVE PAYMENT + ENROLLMENT
    # --------------------------------------------------------

    try:

        db.session.commit()

    except Exception as error:

        db.session.rollback()

        print("==========================================")
        print("PAYMENT COMPLETION ERROR")
        print("Error Type:", type(error).__name__)
        print("Error:", repr(error))
        print("==========================================")

        return jsonify({
            "success": False,
            "message": (
                "Payment was verified but "
                "enrollment could not be saved."
            ),
        }), 500

    # --------------------------------------------------------
    # SUCCESS LOG
    # --------------------------------------------------------

    print("==========================================")
    print("RAZORPAY PAYMENT SUCCESS")
    print("User ID:", session["user_id"])
    print("Course ID:", course_id)
    print("Order ID:", razorpay_order_id)
    print("Payment ID:", razorpay_payment_id)
    print("==========================================")

    # --------------------------------------------------------
    # RETURN SUCCESS
    # --------------------------------------------------------

    return jsonify({
        "success": True,
        "message": "Payment successful. Course unlocked.",
        "redirect_url": url_for("student_dashboard"),
    })


# ============================================================
# PAYMENT CANCELLED
# ============================================================

@app.route(
    "/payment/cancel/<int:course_id>"
)
@login_required
def payment_cancel(course_id):

    flash(
        "Payment was cancelled.",
        "warning",
    )

    return redirect(
        url_for(
            "course_details",
            course_id=course_id,
        )
    )


# ============================================================
# STUDENT DASHBOARD
# ============================================================

@app.route("/student/dashboard")
@login_required
def student_dashboard():

    if session.get("role") == "admin":

        return redirect(
            url_for("admin_dashboard")
        )

    user = User.query.get_or_404(
        session["user_id"]
    )

    enrollments = (
        Enrollment.query
        .filter_by(user_id=user.id)
        .order_by(Enrollment.id.desc())
        .all()
    )

    return render_template(
        "student_dashboard.html",
        user=user,
        enrollments=enrollments,
    )


# ============================================================
# OLD FREE ENROLL ROUTE
# ============================================================

@app.route(
    "/enroll/<int:course_id>",
    methods=["POST"],
)
@login_required
def enroll(course_id):

    if session.get("role") == "admin":

        flash(
            "Administrators cannot enroll in courses.",
            "warning",
        )

        return redirect(
            url_for(
                "course_details",
                course_id=course_id,
            )
        )

    course = Course.query.get_or_404(course_id)

    existing = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course.id,
    ).first()

    if existing:

        flash(
            "You are already enrolled in this course.",
            "info",
        )

        return redirect(
            url_for(
                "course_details",
                course_id=course.id,
            )
        )

    if float(course.price or 0) > 0:

        flash(
            "Please complete payment to enroll in this course.",
            "warning",
        )

        return redirect(
            url_for(
                "course_details",
                course_id=course.id,
            )
        )

    enrollment = Enrollment(
        user_id=session["user_id"],
        course_id=course.id,
        progress=0,
        completed=False,
    )

    try:
        db.session.add(enrollment)
        db.session.commit()

    except Exception as error:
        db.session.rollback()
        print("Enrollment error:", error)

        flash(
            "Unable to enroll in this course.",
            "danger",
        )

        return redirect(
            url_for(
                "course_details",
                course_id=course.id,
            )
        )

    flash(
        f"You have successfully enrolled in {course.title}.",
        "success",
    )

    return redirect(
        url_for("student_dashboard")
    )


# ============================================================
# COURSE LEARNING
# ============================================================

def _get_active_course_videos(course_id):
    """Return the videos currently visible to students."""
    return (
        CourseVideo.query
        .filter(
            CourseVideo.course_id == course_id,
            or_(
                CourseVideo.is_active.is_(True),
                CourseVideo.is_active.is_(None),
            ),
            )
        .order_by(
            CourseVideo.sort_order.asc(),
            CourseVideo.id.asc(),
        )
        .all()
    )


def _calculate_course_progress(enrollment, videos=None):
    """
    Calculate progress from completed individual videos.

    This is intentionally based on active videos, so when an admin
    uploads a new lesson the denominator increases automatically
    while already completed lessons remain completed.
    """
    if videos is None:
        videos = _get_active_course_videos(enrollment.course_id)

    total_videos = len(videos)

    if total_videos == 0:
        enrollment.progress = 0
        enrollment.completed = False
        return 0, 0, total_videos

    video_ids = {video.id for video in videos}

    watched_records = (
        CourseVideoProgress.query
        .filter_by(
            user_id=enrollment.user_id,
            course_id=enrollment.course_id,
        )
        .all()
    )

    watched_ids = {
        record.video_id
        for record in watched_records
        if record.video_id in video_ids
    }

    watched_count = len(watched_ids)

    progress = int(
        round((watched_count / total_videos) * 100)
    )

    progress = max(0, min(100, progress))

    enrollment.progress = progress
    enrollment.completed = (
            watched_count == total_videos
    )

    return progress, watched_count, total_videos


def _load_student_course(course_id):
    """Load an enrolled course, active videos and watched video IDs."""

    course = Course.query.get_or_404(course_id)

    user_id = session.get("user_id")
    if not user_id:
        return None, None, [], set()

    enrollment = Enrollment.query.filter_by(
        user_id=user_id,
        course_id=course.id,
    ).first()

    if not enrollment:
        return course, None, [], set()

    videos = _get_active_course_videos(course.id)

    # Remove progress records belonging to deleted/hidden videos from
    # the calculation, but keep the records themselves so history is safe.
    progress, watched_count, total_videos = _calculate_course_progress(
        enrollment,
        videos,
    )

    try:
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Course progress sync error:", error)

    active_video_ids = {video.id for video in videos}

    watched_records = (
        CourseVideoProgress.query
        .filter_by(
            user_id=user_id,
            course_id=course.id,
        )
        .all()
    )

    watched_video_ids = {
        record.video_id
        for record in watched_records
        if record.video_id in active_video_ids
    }

    return course, enrollment, videos, watched_video_ids


@app.route("/learn/<int:course_id>")
@login_required
def learn_course(course_id):
    course, enrollment, videos, watched_video_ids = _load_student_course(
        course_id
    )

    if course is None:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    if enrollment is None:
        flash(
            "Please purchase this course first.",
            "warning",
        )
        return redirect(
            url_for("course_details", course_id=course.id)
        )

    return render_template(
        "student_course.html",
        course=course,
        enrollment=enrollment,
        videos=videos,
        watched_video_ids=watched_video_ids,
    )


@app.route("/student/course/<int:course_id>/learn")
@login_required
def student_learn_course(course_id):
    # Compatibility route for existing student-dashboard links.
    course, enrollment, videos, watched_video_ids = _load_student_course(
        course_id
    )

    if course is None:
        flash("Please login first.", "warning")
        return redirect(url_for("login"))

    if enrollment is None:
        flash(
            "You are not enrolled in this course.",
            "danger",
        )
        return redirect(url_for("courses"))

    return render_template(
        "student_course.html",
        course=course,
        enrollment=enrollment,
        videos=videos,
        watched_video_ids=watched_video_ids,
    )


# ============================================================
# SERVE UPLOADED VIDEOS
# ============================================================

@app.route(
    "/uploads/videos/<path:filename>"
)
@login_required
def uploaded_video(filename):

    video = (
        CourseVideo.query
        .filter(
            CourseVideo.video_file == filename,
            or_(
                CourseVideo.is_active.is_(True),
                CourseVideo.is_active.is_(None),
            ),
            )
        .first()
    )

    if not video:
        return "Video not found.", 404

    if session.get("role") != "admin":

        enrollment = Enrollment.query.filter_by(
            user_id=session["user_id"],
            course_id=video.course_id,
        ).first()

        if not enrollment:
            return (
                "You are not enrolled in this course.",
                403,
            )

    file_path = os.path.join(
        app.config["VIDEO_UPLOAD_FOLDER"],
        video.video_file,
    )

    if not os.path.isfile(file_path):
        return "Video file not found on server.", 404

    # Choose a useful MIME type from the actual filename.
    extension = (
        video.video_file.rsplit(".", 1)[1].lower()
        if "." in video.video_file
        else "mp4"
    )

    mime_types = {
        "mp4": "video/mp4",
        "webm": "video/webm",
        "ogg": "video/ogg",
        "ogv": "video/ogg",
        "mov": "video/quicktime",
        "m4v": "video/x-m4v",
    }

    response = send_file(
        file_path,
        mimetype=mime_types.get(
            extension,
            "application/octet-stream",
        ),
        as_attachment=False,
        conditional=True,
        etag=True,
        max_age=0,
    )

    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Content-Disposition"] = "inline"
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"

    return response


# ============================================================
# MARK ONE VIDEO AS COMPLETED
# ============================================================

@app.route(
    "/course/<int:course_id>/video/<int:video_id>/complete",
    methods=["POST"],
)
@login_required
def complete_course_video(course_id, video_id):
    """Mark one video as watched and recalculate course progress."""

    if session.get("role") == "admin":
        return jsonify({
            "success": False,
            "message": "Administrators do not have student progress.",
        }), 403

    enrollment = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course_id,
    ).first()

    if not enrollment:
        return jsonify({
            "success": False,
            "message": "You are not enrolled in this course.",
        }), 403

    video = CourseVideo.query.filter(
        CourseVideo.id == video_id,
        CourseVideo.course_id == course_id,
        or_(
            CourseVideo.is_active.is_(True),
            CourseVideo.is_active.is_(None),
        ),
        ).first()

    if not video:
        return jsonify({
            "success": False,
            "message": "Course video not found.",
        }), 404

    existing = CourseVideoProgress.query.filter_by(
        user_id=session["user_id"],
        course_id=course_id,
        video_id=video_id,
    ).first()

    if not existing:
        existing = CourseVideoProgress(
            user_id=session["user_id"],
            course_id=course_id,
            video_id=video_id,
            watched_at=datetime.utcnow(),
        )
        db.session.add(existing)

    progress, watched_count, total_videos = _calculate_course_progress(
        enrollment
    )

    try:
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Video progress save error:", error)

        return jsonify({
            "success": False,
            "message": "Unable to save video progress.",
        }), 500

    watched_video_ids = [
        record.video_id
        for record in CourseVideoProgress.query.filter_by(
            user_id=session["user_id"],
            course_id=course_id,
        ).all()
    ]

    return jsonify({
        "success": True,
        "message": "Video completed.",
        "video_id": video_id,
        "progress": progress,
        "watched_count": watched_count,
        "total_videos": total_videos,
        "completed": enrollment.completed,
        "watched_video_ids": watched_video_ids,
    })


# ============================================================
# GET CURRENT COURSE PROGRESS
# ============================================================

@app.route(
    "/course/<int:course_id>/progress/status",
    methods=["GET"],
)
@login_required
def course_progress_status(course_id):
    """Return the current progress and watched videos for the student."""

    enrollment = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course_id,
    ).first_or_404()

    videos = _get_active_course_videos(course_id)

    progress, watched_count, total_videos = _calculate_course_progress(
        enrollment,
        videos,
    )

    try:
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Progress status sync error:", error)

    active_video_ids = {video.id for video in videos}

    watched_video_ids = [
        record.video_id
        for record in CourseVideoProgress.query.filter_by(
            user_id=session["user_id"],
            course_id=course_id,
        ).all()
        if record.video_id in active_video_ids
    ]

    return jsonify({
        "success": True,
        "progress": progress,
        "watched_count": watched_count,
        "total_videos": total_videos,
        "completed": enrollment.completed,
        "watched_video_ids": watched_video_ids,
    })


# ============================================================
# UPDATE COURSE PROGRESS - COMPATIBILITY ROUTE
# ============================================================

@app.route(
    "/course/<int:course_id>/progress",
    methods=["POST"],
)
@login_required
def update_progress(course_id):

    enrollment = Enrollment.query.filter_by(
        user_id=session["user_id"],
        course_id=course_id,
    ).first_or_404()

    # New frontend sends video_id. Use the individual video completion
    # system instead of trusting an arbitrary percentage from the browser.
    video_id = request.form.get("video_id")

    if not video_id:
        data = request.get_json(silent=True) or {}
        video_id = data.get("video_id")

    if video_id:
        try:
            video_id = int(video_id)
        except (ValueError, TypeError):
            video_id = None

    if video_id:
        return complete_course_video(course_id, video_id)

    # Keep old manual progress forms working when no video_id is supplied.
    try:
        progress = int(
            request.form.get(
                "progress",
                0,
            )
        )
    except (ValueError, TypeError):
        progress = 0

    progress = max(
        0,
        min(100, progress),
    )

    enrollment.progress = progress
    enrollment.completed = progress >= 100

    try:
        db.session.commit()
    except Exception as error:
        db.session.rollback()
        print("Legacy progress update error:", error)
        return jsonify({
            "success": False,
            "message": "Unable to update course progress.",
        }), 500

    if request.is_json:
        return jsonify({
            "success": True,
            "progress": progress,
            "completed": enrollment.completed,
        })

    flash(
        "Course progress updated.",
        "success",
    )

    return redirect(
        url_for("student_dashboard")
    )


# ============================================================
# ADMIN - HEADER / BRANDING SETTINGS
# ============================================================

@app.route(
    "/admin/branding",
    methods=["GET", "POST"],
)
@admin_required
def admin_branding():

    current_name = get_site_setting(
        "site_name",
        "NIKSS Coding Hub",
    )

    current_logo = get_site_setting(
        "site_logo",
        "",
    )

    if request.method == "POST":

        site_name = request.form.get(
            "site_name",
            "NIKSS Coding Hub",
        ).strip()

        if not site_name:
            flash(
                "Website name is required.",
                "danger",
            )

            return redirect(url_for("admin_branding"))

        if len(site_name) > 100:
            site_name = site_name[:100]

        name_setting = SiteSetting.query.filter_by(
            setting_key="site_name"
        ).first()

        if not name_setting:
            name_setting = SiteSetting(
                setting_key="site_name"
            )
            db.session.add(name_setting)

        name_setting.setting_value = site_name

        logo_file = request.files.get("site_logo")

        if logo_file and logo_file.filename:
            try:
                new_logo = save_uploaded_image(
                    logo_file,
                    "site_logo",
                )

                logo_setting = SiteSetting.query.filter_by(
                    setting_key="site_logo"
                ).first()

                if not logo_setting:
                    logo_setting = SiteSetting(
                        setting_key="site_logo"
                    )
                    db.session.add(logo_setting)

                old_logo = logo_setting.setting_value
                logo_setting.setting_value = new_logo

                db.session.flush()

                if old_logo and old_logo != new_logo:
                    remove_uploaded_image(old_logo)

            except (ValueError, OSError) as error:
                db.session.rollback()
                flash(str(error), "danger")
                return redirect(url_for("admin_branding"))

        try:
            db.session.commit()
        except Exception as error:
            db.session.rollback()
            print("Branding update error:", error)

            flash(
                "Unable to update header settings.",
                "danger",
            )

            return redirect(url_for("admin_branding"))

        flash(
            "Header branding updated successfully.",
            "success",
        )

        return redirect(url_for("admin_branding"))

    return render_template(
        "admin_branding.html",
        site_name=current_name,
        site_logo=current_logo,
    )


# ============================================================
# ADMIN DASHBOARD
# ============================================================

@app.route("/admin")
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():

    users = (
        User.query
        .order_by(User.created_at.desc())
        .all()
    )

    students = (
        User.query
        .filter_by(role="student")
        .order_by(User.created_at.desc())
        .all()
    )

    student_count = User.query.filter_by(
        role="student"
    ).count()

    admin_count = User.query.filter_by(
        role="admin"
    ).count()

    total_users = User.query.count()

    total_courses = Course.query.count()

    active_courses = Course.query.filter_by(
        is_active=True
    ).count()

    total_enrollments = Enrollment.query.count()

    completed_enrollments = (
        Enrollment.query
        .filter_by(completed=True)
        .count()
    )

    total_messages = ContactMessage.query.count()

    unread_messages = (
        ContactMessage.query
        .filter_by(is_read=False)
        .count()
    )

    messages = (
        ContactMessage.query
        .order_by(ContactMessage.created_at.desc())
        .all()
    )

    courses = (
        Course.query
        .order_by(Course.id.desc())
        .all()
    )

    enrollments = (
        Enrollment.query
        .order_by(Enrollment.id.desc())
        .all()
    )

    # --------------------------------------------------------
    # PAYMENT INFORMATION
    # --------------------------------------------------------

    total_payments = Payment.query.count()

    successful_payments = Payment.query.filter_by(
        status="paid"
    ).count()

    failed_payments = Payment.query.filter_by(
        status="failed"
    ).count()

    pending_payments = Payment.query.filter_by(
        status="created"
    ).count()

    total_revenue = (
            db.session.query(
                db.func.sum(Payment.amount)
            )
            .filter(Payment.status == "paid")
            .scalar()
            or 0
    )

    payments = (
        Payment.query
        .order_by(Payment.id.desc())
        .all()
    )

    # --------------------------------------------------------
    # VIDEO INFORMATION
    # --------------------------------------------------------

    total_videos = CourseVideo.query.count()

    active_videos = CourseVideo.query.filter_by(
        is_active=True
    ).count()

    # --------------------------------------------------------
    # CHATBOT INFORMATION
    # --------------------------------------------------------

    total_chat_messages = ChatMessage.query.count()

    total_chatbot_leads = ChatbotLead.query.count()

    chatbot_leads = (
        ChatbotLead.query
        .order_by(ChatbotLead.id.desc())
        .all()
    )

    # --------------------------------------------------------
    # SINGLE TEMPLATE RETURN
    # --------------------------------------------------------

    return render_template(
        "admin_dashboard.html",

        users=users,
        students=students,

        student_count=student_count,
        admin_count=admin_count,
        total_users=total_users,
        total_students=student_count,

        total_courses=total_courses,
        active_courses=active_courses,

        total_enrollments=total_enrollments,
        completed_enrollments=completed_enrollments,

        total_messages=total_messages,
        unread_messages=unread_messages,

        contact_messages=messages,
        messages=messages,

        courses=courses,
        enrollments=enrollments,

        payments=payments,
        total_payments=total_payments,
        successful_payments=successful_payments,
        failed_payments=failed_payments,
        pending_payments=pending_payments,
        total_revenue=total_revenue,

        total_videos=total_videos,
        active_videos=active_videos,

        total_chat_messages=total_chat_messages,
        total_chatbot_leads=total_chatbot_leads,
        chatbot_leads=chatbot_leads,
    )


# ============================================================
# ADMIN - CHATBOT LEADS
# ============================================================

@app.route("/admin/chatbot-leads")
@admin_required
def admin_chatbot_leads():

    leads = (
        ChatbotLead.query
        .order_by(ChatbotLead.created_at.desc())
        .all()
    )

    return render_template(
        "admin_chatbot_leads.html",
        leads=leads,
    )


# ============================================================
# ADMIN - CHAT HISTORY
# ============================================================

@app.route("/admin/chat-history")
@admin_required
def admin_chat_history():

    chats = (
        ChatMessage.query
        .order_by(ChatMessage.created_at.desc())
        .all()
    )

    return render_template(
        "admin_chat_history.html",
        chats=chats,
    )


# ============================================================
# ADMIN - ALL CONTACT MESSAGES
# ============================================================

@app.route("/admin/messages")
@admin_required
def admin_messages():

    messages = (
        ContactMessage.query
        .order_by(ContactMessage.created_at.desc())
        .all()
    )

    return render_template(
        "admin_messages.html",
        messages=messages,
    )


# ============================================================
# ADMIN - MARK CONTACT MESSAGE AS READ
# ============================================================

@app.route(
    "/admin/message/<int:message_id>/read",
    methods=["POST"],
)
@admin_required
def admin_mark_message_read(message_id):

    contact_message = ContactMessage.query.get_or_404(
        message_id
    )

    contact_message.is_read = True

    db.session.commit()

    flash(
        "Message marked as read.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - DELETE CONTACT MESSAGE
# ============================================================

@app.route(
    "/admin/message/<int:message_id>/delete",
    methods=["POST"],
)
@admin_required
def admin_delete_message(message_id):

    contact_message = ContactMessage.query.get_or_404(
        message_id
    )

    db.session.delete(contact_message)
    db.session.commit()

    flash(
        "Message deleted successfully.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - ADD COURSE
# ============================================================

@app.route(
    "/admin/course/add",
    methods=["GET", "POST"],
)
@admin_required
def admin_add_course():

    if request.method == "POST":

        title = request.form.get(
            "title",
            "",
        ).strip()

        description = request.form.get(
            "description",
            "",
        ).strip()

        price_value = request.form.get(
            "price",
            "0",
        ).strip()

        level = request.form.get(
            "level",
            "Beginner",
        ).strip()

        duration = request.form.get(
            "duration",
            "8 Weeks",
        ).strip()

        if not title or not description:

            flash(
                "Course title and description are required.",
                "danger",
            )

            return redirect(
                url_for("admin_add_course")
            )

        try:

            price = float(price_value or 0)
            price = max(0, price)

        except (ValueError, TypeError):

            price = 0

        poster_file = request.files.get("poster_image")
        image = None

        if poster_file and poster_file.filename:
            try:
                image = save_uploaded_image(
                    poster_file,
                    "course_poster",
                )
            except (ValueError, OSError) as error:
                flash(str(error), "danger")
                return redirect(url_for("admin_add_course"))

        course = Course(
            title=title,
            description=description,
            price=price,
            image=image,
            level=level or "Beginner",
            duration=duration or "8 Weeks",
            is_active=True,
        )

        try:
            db.session.add(course)
            db.session.commit()

        except Exception as error:
            db.session.rollback()
            print("Add course error:", error)

            flash(
                "Unable to add course.",
                "danger",
            )

            return redirect(
                url_for("admin_add_course")
            )

        flash(
            "Course added successfully.",
            "success",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    return render_template(
        "admin_add_course.html"
    )


# ============================================================
# ADMIN - EDIT COURSE
# ============================================================

@app.route(
    "/admin/course/<int:course_id>/edit",
    methods=["GET", "POST"],
)
@admin_required
def admin_edit_course(course_id):

    course = Course.query.get_or_404(course_id)

    if request.method == "POST":

        title = request.form.get(
            "title",
            course.title,
        ).strip()

        description = request.form.get(
            "description",
            course.description,
        ).strip()

        price_value = request.form.get(
            "price",
            str(course.price or 0),
        ).strip()

        try:

            price = float(price_value)
            course.price = max(0, price)

        except (ValueError, TypeError):

            course.price = 0

        if not title or not description:

            flash(
                "Course title and description are required.",
                "danger",
            )

            return redirect(
                url_for(
                    "admin_edit_course",
                    course_id=course.id,
                )
            )

        course.title = title
        course.description = description

        poster_file = request.files.get("poster_image")

        old_course_image = None

        if poster_file and poster_file.filename:
            try:
                new_image = save_uploaded_image(
                    poster_file,
                    f"course_{course.id}",
                )

                old_course_image = course.image
                course.image = new_image

            except (ValueError, OSError) as error:
                flash(str(error), "danger")
                return redirect(
                    url_for(
                        "admin_edit_course",
                        course_id=course.id,
                    )
                )

        course.level = request.form.get(
            "level",
            course.level or "Beginner",
            ).strip()

        course.duration = request.form.get(
            "duration",
            course.duration or "8 Weeks",
            ).strip()

        try:
            db.session.commit()

        except Exception as error:
            db.session.rollback()
            print("Edit course error:", error)

            flash(
                "Unable to update course.",
                "danger",
            )

            return redirect(
                url_for(
                    "admin_edit_course",
                    course_id=course.id,
                )
            )

        if old_course_image and old_course_image != course.image:
            remove_uploaded_image(old_course_image)

        flash(
            "Course updated successfully.",
            "success",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    return render_template(
        "admin_edit_course.html",
        course=course,
    )


# ============================================================
# ADMIN - DELETE COURSE
# ============================================================

@app.route(
    "/admin/course/<int:course_id>/delete",
    methods=["POST"],
)
@admin_required
def admin_delete_course(course_id):

    course = Course.query.get_or_404(course_id)

    videos = CourseVideo.query.filter_by(
        course_id=course.id
    ).all()

    for video in videos:

        if video.video_file:

            file_path = os.path.join(
                app.config["VIDEO_UPLOAD_FOLDER"],
                video.video_file,
            )

            if os.path.isfile(file_path):

                try:
                    os.remove(file_path)

                except OSError as error:

                    print(
                        "Could not delete video file:",
                        error,
                    )

    Enrollment.query.filter_by(
        course_id=course.id
    ).delete(
        synchronize_session=False
    )

    Payment.query.filter_by(
        course_id=course.id
    ).delete(
        synchronize_session=False
    )

    CourseVideo.query.filter_by(
        course_id=course.id
    ).delete(
        synchronize_session=False
    )

    # Delete the uploaded course poster, if this course has one.
    if course.image:
        remove_uploaded_image(course.image)

    try:
        db.session.delete(course)
        db.session.commit()

    except Exception as error:
        db.session.rollback()
        print("Delete course error:", error)

        flash(
            "Unable to delete course.",
            "danger",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    flash(
        "Course and its videos deleted successfully.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - TOGGLE COURSE
# ============================================================

@app.route(
    "/admin/course/<int:course_id>/toggle",
    methods=["POST"],
)
@admin_required
def admin_toggle_course(course_id):

    course = Course.query.get_or_404(course_id)

    course.is_active = not course.is_active

    db.session.commit()

    if course.is_active:

        flash(
            "Course activated.",
            "success",
        )

    else:

        flash(
            "Course deactivated.",
            "warning",
        )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - UPLOAD / ADD VIDEO
# ============================================================
@app.route(
    "/admin/course/<int:course_id>/upload-video",
    methods=["GET", "POST"]
)
@admin_required
def admin_upload_video(course_id):

    # --------------------------------------------------------
    # GET COURSE
    # --------------------------------------------------------

    course = Course.query.get_or_404(course_id)

    # --------------------------------------------------------
    # POST - UPLOAD VIDEO
    # --------------------------------------------------------

    if request.method == "POST":

        video_title = request.form.get(
            "video_title",
            ""
        ).strip()

        video_url = request.form.get(
            "video_url",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        duration = request.form.get(
            "duration",
            ""
        ).strip()

        sort_order_value = request.form.get(
            "sort_order",
            "0"
        ).strip()

        # ----------------------------------------------------
        # SORT ORDER
        # ----------------------------------------------------

        try:
            sort_order = int(sort_order_value or 0)

        except (ValueError, TypeError):
            sort_order = 0

        # No lesson number = append after existing lessons.
        if sort_order <= 0:
            last_sort_order = (
                db.session.query(
                    db.func.max(CourseVideo.sort_order)
                )
                .filter(
                    CourseVideo.course_id == course.id
                )
                .scalar()
            )
            sort_order = int(last_sort_order or 0) + 1

        # ----------------------------------------------------
        # GET FILE
        # ----------------------------------------------------

        video_file = request.files.get("video_file")

        saved_filename = None

        if not video_title and not video_url and not (
                video_file and video_file.filename
        ):
            flash(
                "Please enter a video title and provide a video URL or upload a video file.",
                "danger",
            )
            return redirect(
                url_for(
                    "admin_upload_video",
                    course_id=course.id,
                )
            )

        # ----------------------------------------------------
        # UPLOAD VIDEO FILE
        # ----------------------------------------------------

        if video_file and video_file.filename:

            # Check extension
            if not allowed_video_file(video_file.filename):

                flash(
                    "Invalid video format. Allowed: MP4, WebM, OGG, MOV, M4V.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_upload_video",
                        course_id=course.id
                    )
                )

            # Secure original filename
            original_name = secure_filename(
                video_file.filename
            )

            if not original_name:

                flash(
                    "Invalid video filename.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_upload_video",
                        course_id=course.id
                    )
                )

            # ------------------------------------------------
            # GET EXTENSION
            # ------------------------------------------------

            extension = original_name.rsplit(
                ".",
                1
            )[1].lower()

            # ------------------------------------------------
            # CREATE UNIQUE FILE NAME
            # ------------------------------------------------

            saved_filename = (
                f"{course.id}_"
                f"{uuid4().hex}_"
                f"{original_name}"
            )

            # Make sure extension exists
            if not saved_filename.lower().endswith(
                    f".{extension}"
            ):
                saved_filename += f".{extension}"

            # ------------------------------------------------
            # UPLOAD FOLDER
            # ------------------------------------------------

            upload_folder = app.config.get(
                "VIDEO_UPLOAD_FOLDER"
            )

            if not upload_folder:

                upload_folder = os.path.join(
                    app.root_path,
                    "static",
                    "uploads",
                    "videos"
                )

                app.config["VIDEO_UPLOAD_FOLDER"] = (
                    upload_folder
                )

            # Create folder if it doesn't exist
            os.makedirs(
                upload_folder,
                exist_ok=True
            )

            # ------------------------------------------------
            # SAVE FILE
            # ------------------------------------------------

            save_path = os.path.join(
                upload_folder,
                saved_filename
            )

            try:

                video_file.save(save_path)

            except Exception as error:

                print(
                    "VIDEO UPLOAD ERROR:",
                    error
                )

                flash(
                    "Unable to save video file.",
                    "danger"
                )

                return redirect(
                    url_for(
                        "admin_upload_video",
                        course_id=course.id
                    )
                )

        # ----------------------------------------------------
        # REQUIRE URL OR FILE
        # ----------------------------------------------------

        if not video_url and not saved_filename:

            flash(
                "Please provide a video URL or upload a video file.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_upload_video",
                    course_id=course.id
                )
            )

        # ----------------------------------------------------
        # CREATE COURSE VIDEO
        # ----------------------------------------------------

        video = CourseVideo(
            course_id=course.id,

            title=(
                video_title
                if video_title
                else "Untitled Video"
            ),

            video_url=(
                video_url
                if video_url
                else None
            ),

            video_file=saved_filename,

            description=description,

            duration=duration,

            sort_order=sort_order,

            is_active=True
        )

        # ----------------------------------------------------
        # SAVE DATABASE
        # ----------------------------------------------------

        try:

            db.session.add(video)

            db.session.commit()

            print(
                "VIDEO SAVED:",
                "id=", video.id,
                "course_id=", video.course_id,
                "title=", video.title,
                "video_file=", video.video_file,
                "video_url=", video.video_url,
                "is_active=", video.is_active,
            )

        except Exception as error:

            db.session.rollback()

            # -----------------------------------------------
            # DELETE FILE IF DATABASE FAILED
            # -----------------------------------------------

            if saved_filename:

                upload_folder = app.config.get(
                    "VIDEO_UPLOAD_FOLDER"
                )

                if upload_folder:

                    file_path = os.path.join(
                        upload_folder,
                        saved_filename
                    )

                    if os.path.isfile(file_path):

                        try:
                            os.remove(file_path)

                        except OSError:
                            pass

            print(
                "VIDEO DATABASE ERROR:",
                error
            )

            flash(
                "Unable to add course video.",
                "danger"
            )

            return redirect(
                url_for(
                    "admin_upload_video",
                    course_id=course.id
                )
            )

        # ----------------------------------------------------
        # SUCCESS
        # ----------------------------------------------------

        flash(
            "Course video added successfully.",
            "success"
        )

        return redirect(
            url_for(
                "admin_upload_video",
                course_id=course.id
            )
        )

    # --------------------------------------------------------
    # GET - SHOW UPLOAD PAGE
    # --------------------------------------------------------

    videos = (
        CourseVideo.query
        .filter_by(
            course_id=course.id
        )
        .order_by(
            CourseVideo.sort_order.asc(),
            CourseVideo.id.asc()
        )
        .all()
    )

    return render_template(
        "admin_upload_video.html",
        course=course,
        videos=videos
    )
# ============================================================
# ADMIN - DELETE VIDEO
# ============================================================

@app.route(
    "/admin/video/<int:video_id>/delete",
    methods=["POST"],
)
@admin_required
def admin_delete_video(video_id):

    video = CourseVideo.query.get_or_404(video_id)

    course_id = video.course_id

    if video.video_file:

        file_path = os.path.join(
            app.config["VIDEO_UPLOAD_FOLDER"],
            video.video_file,
        )

        if os.path.isfile(file_path):

            try:
                os.remove(file_path)

            except OSError as error:

                print(
                    "Video file deletion error:",
                    error,
                )

    try:

        db.session.delete(video)
        db.session.commit()

    except Exception as error:

        db.session.rollback()

        print(
            "Video database deletion error:",
            error,
        )

        flash(
            "Unable to delete video.",
            "danger",
        )

        return redirect(
            url_for(
                "admin_upload_video",
                course_id=course_id,
            )
        )

    flash(
        "Video deleted successfully.",
        "success",
    )

    return redirect(
        url_for(
            "admin_upload_video",
            course_id=course_id,
        )
    )


# ============================================================
# ADMIN - TOGGLE VIDEO
# ============================================================

@app.route(
    "/admin/video/<int:video_id>/toggle",
    methods=["POST"],
)
@admin_required
def admin_toggle_video(video_id):

    video = CourseVideo.query.get_or_404(video_id)

    video.is_active = not video.is_active

    db.session.commit()

    if video.is_active:

        flash(
            "Video activated.",
            "success",
        )

    else:

        flash(
            "Video hidden from students.",
            "warning",
        )

    return redirect(
        url_for(
            "admin_upload_video",
            course_id=video.course_id,
        )
    )

# ============================================================
# ADMIN - VIEW STUDENT
# ============================================================

@app.route(
    "/admin/student/<int:user_id>"
)
@admin_required
def admin_student_details(user_id):

    user = User.query.get_or_404(user_id)

    enrollments = (
        Enrollment.query
        .filter_by(user_id=user.id)
        .order_by(Enrollment.id.desc())
        .all()
    )

    payments = (
        Payment.query
        .filter_by(user_id=user.id)
        .order_by(Payment.id.desc())
        .all()
    )

    return render_template(
        "admin_student_details.html",
        user=user,
        enrollments=enrollments,
        payments=payments,
    )


# ============================================================
# ADMIN - DELETE STUDENT
# ============================================================

@app.route(
    "/admin/student/<int:user_id>/delete",
    methods=["POST"],
)
@admin_required
def admin_delete_student(user_id):

    user = User.query.get_or_404(user_id)

    if user.role == "admin":

        flash(
            "Admin accounts cannot be deleted here.",
            "danger",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    # The User relationships use delete-orphan for:
    # Enrollment, Payment, ChatMessage and ChatbotLead.
    # Therefore deleting the user also deletes those records.
    try:

        db.session.delete(user)
        db.session.commit()

    except Exception as error:

        db.session.rollback()

        print(
            "Delete student error:",
            error,
        )

        flash(
            "Unable to delete student.",
            "danger",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    flash(
        "Student deleted successfully.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - UPDATE ENROLLMENT PROGRESS
# ============================================================

@app.route(
    "/admin/enrollment/<int:enrollment_id>/progress",
    methods=["POST"],
)
@admin_required
def admin_update_progress(enrollment_id):

    enrollment = Enrollment.query.get_or_404(
        enrollment_id
    )

    try:

        progress = int(
            request.form.get(
                "progress",
                enrollment.progress,
            )
        )

    except (ValueError, TypeError):

        progress = enrollment.progress

    progress = max(
        0,
        min(100, progress),
    )

    enrollment.progress = progress
    enrollment.completed = progress >= 100

    db.session.commit()

    flash(
        "Student course progress updated.",
        "success",
    )

    return redirect(
        url_for("admin_dashboard")
    )


# ============================================================
# ADMIN - CREATE ADMIN
# ============================================================

@app.route(
    "/admin/create-admin",
    methods=["GET", "POST"],
)
@admin_required
def create_admin():

    if request.method == "POST":

        name = request.form.get(
            "name",
            "",
        ).strip()

        email = request.form.get(
            "email",
            "",
        ).strip().lower()

        password = request.form.get(
            "password",
            "",
        )

        confirm_password = request.form.get(
            "confirm_password",
            "",
        )

        if not name or not email or not password:

            flash(
                "All fields are required.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        if "@" not in email:

            flash(
                "Please enter a valid email address.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        if password != confirm_password:

            flash(
                "Passwords do not match.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        existing = User.query.filter_by(
            email=email
        ).first()

        if existing:

            flash(
                "This email is already registered.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        admin_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password),
            role="admin",
        )

        try:

            db.session.add(admin_user)
            db.session.commit()

        except Exception as error:

            db.session.rollback()

            print(
                "Create admin error:",
                error,
            )

            flash(
                "Unable to create admin.",
                "danger",
            )

            return redirect(
                url_for("create_admin")
            )

        flash(
            "New admin created successfully.",
            "success",
        )

        return redirect(
            url_for("admin_dashboard")
        )

    return render_template("create_admin.html")


# ============================================================
# ADMIN INITIALIZATION
# ============================================================

def create_default_admin():

    with app.app_context():
        # These are the only Google accounts pre-configured as administrators.
        # ADMIN_GOOGLE_EMAILS can override this list in production if needed.
        admin_emails = sorted(ADMIN_GOOGLE_EMAILS)

        admin_password = os.getenv(
            "ADMIN_PASSWORD",
            "Admin@123",
        )

        admin_name = os.getenv(
            "ADMIN_NAME",
            "NIKSS Admin",
        )

        for admin_email in admin_emails:
            admin = User.query.filter_by(
                email=admin_email
            ).first()

            if not admin:
                admin = User(
                    name=admin_name,
                    email=admin_email,
                    password=generate_password_hash(admin_password),
                    role="admin",
                    mobile=None,
                    mobile_verified=False,
                )
                db.session.add(admin)
            elif admin.role != "admin":
                admin.role = "admin"

        db.session.commit()

        print("Google admin accounts configured: %d" % len(admin_emails))


def create_default_courses():

    with app.app_context():

        if Course.query.count() > 0:
            return

        courses = [

            Course(
                title="Python Programming",
                description=(
                    "Learn Python programming from "
                    "the basics to practical application "
                    "development."
                ),
                price=4999,
                image="python.jpg",
                level="Beginner",
                duration="8 Weeks",
                is_active=True,
            ),

            Course(
                title="Cybersecurity",
                description=(
                    "Understand cybersecurity fundamentals, "
                    "networking, security concepts and "
                    "practical security tools."
                ),
                price=6999,
                image="cybersecurity.jpg",
                level="Beginner",
                duration="10 Weeks",
                is_active=True,
            ),

            Course(
                title="Web Development",
                description=(
                    "Build responsive websites using "
                    "HTML, CSS, JavaScript and Flask."
                ),
                price=5999,
                image="web-development.jpg",
                level="Beginner",
                duration="8 Weeks",
                is_active=True,
            ),

            Course(
                title="Data Analytics",
                description=(
                    "Learn data analysis, visualization, "
                    "Python and practical data projects."
                ),
                price=5999,
                image="data-analytics.jpg",
                level="Intermediate",
                duration="8 Weeks",
                is_active=True,
            ),

            Course(
                title="Computer Networking",
                description=(
                    "Learn networking fundamentals, "
                    "protocols, ports, IP addressing and "
                    "network security concepts."
                ),
                price=3999,
                image="networking.jpg",
                level="Beginner",
                duration="6 Weeks",
                is_active=True,
            ),

            Course(
                title="Python Flask Development",
                description=(
                    "Build dynamic web applications with "
                    "Python, Flask, databases and modern "
                    "web technologies."
                ),
                price=5999,
                image="flask.jpg",
                level="Intermediate",
                duration="8 Weeks",
                is_active=True,
            ),
        ]

        db.session.add_all(courses)
        db.session.commit()

        print("Default courses created.")


# ============================================================
# ERROR HANDLER - 413
# ============================================================

@app.errorhandler(413)
def request_entity_too_large(error):

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>File Too Large - NIKSS Coding Hub</title>
    </head>
    <body style="font-family:Arial;text-align:center;padding:80px;">
        <h1>413</h1>
        <h2>Video file is too large</h2>
        <p>Maximum allowed upload size is 500 MB.</p>
        <a href="/admin">Back to Admin Dashboard</a>
    </body>
    </html>
    """, 413


# ============================================================
# ERROR HANDLER - 404
# ============================================================

@app.errorhandler(404)
def page_not_found(error):

    try:

        return render_template(
            "404.html"
        ), 404

    except Exception:

        return """
        <!DOCTYPE html>
        <html>
        <head>
            <title>404 - NIKSS Coding Hub</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 80px;
                    background: #f8fafc;
                }

                h1 {
                    font-size: 80px;
                    color: #2563eb;
                    margin: 0;
                }

                h2 {
                    color: #111827;
                }

                a {
                    display: inline-block;
                    margin-top: 20px;
                    padding: 12px 25px;
                    background: #2563eb;
                    color: white;
                    text-decoration: none;
                    border-radius: 8px;
                }
            </style>
        </head>

        <body>

            <h1>404</h1>

            <h2>Page Not Found</h2>

            <p>
                The requested page does not exist.
            </p>

            <a href="/">
                Back to Home
            </a>

        </body>
        </html>
        """, 404


# ============================================================
# ERROR HANDLER - 500
# ============================================================

@app.errorhandler(500)
def internal_server_error(error):

    db.session.rollback()

    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - NIKSS Coding Hub</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                text-align: center;
                padding: 80px;
                background: #f8fafc;
            }

            h1 {
                font-size: 70px;
                color: #dc2626;
                margin: 0;
            }

            h2 {
                color: #111827;
            }

            a {
                display: inline-block;
                margin-top: 20px;
                padding: 12px 25px;
                background: #2563eb;
                color: white;
                text-decoration: none;
                border-radius: 8px;
            }
        </style>
    </head>

    <body>

        <h1>500</h1>

        <h2>Something went wrong</h2>

        <p>
            Please try again.
        </p>

        <a href="/">
            Back to Home
        </a>

    </body>
    </html>
    """, 500


# ============================================================
# CONTEXT PROCESSOR
# ============================================================

@app.context_processor
def inject_global_data():

    logo_setting = SiteSetting.query.filter_by(
        setting_key="site_logo"
    ).first()

    logo_version = (
        int(logo_setting.updated_at.timestamp())
        if logo_setting and logo_setting.updated_at
        else 0
    )

    return {
        "current_year": datetime.now().year,

        "logged_in": bool(
            session.get("user_id")
        ),

        "current_user_id":
            session.get("user_id"),

        "current_user_role":
            session.get("role"),

        "current_user_name":
            session.get("user_name"),

        "site_name": get_site_setting(
            "site_name",
            "NIKSS Coding Hub",
        ),

        "site_logo": get_site_setting(
            "site_logo",
            "",
        ),

        # Changes whenever the admin saves a new logo.
        # The value is used by base.html as a cache-buster so every
        # browser requests the newest logo immediately.
        "site_logo_version": logo_version,
    }


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    print()
    print("==========================================")
    print("INITIALIZING DATABASE")
    print("==========================================")

    migrate_database()

    create_default_admin()

    create_default_courses()

    print(
        "Database initialization completed."
    )

    print(
        "=========================================="
    )
    print()


# ============================================================
# DATABASE INITIALIZATION FOR GUNICORN / RENDER
# ============================================================
# Gunicorn imports this module instead of executing the
# __main__ block. Therefore the database must be initialized
# during module loading as well.
try:
    initialize_database()
except Exception as error:
    print("Database initialization error:", repr(error))


# ============================================================
# RUN APPLICATION
# ============================================================

if __name__ == "__main__":

    print()
    print("==========================================")
    print("          NIKSS CODING HUB")
    print("==========================================")

    print("Website:")
    print("http://127.0.0.1:5000")
    print()

    print("ADMIN LOGIN")
    print("Email:")
    print(
        os.getenv(
            "ADMIN_EMAIL",
            "admin@niksscodinghub.com",
        )
    )

    print("Password:")
    print(
        os.getenv(
            "ADMIN_PASSWORD",
            "Admin@123",
        )
    )

    print()

    print("Admin Dashboard:")
    print("http://127.0.0.1:5000/admin")
    print()

    print("Razorpay:")

    if RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET and razorpay_client is not None:
        print("Razorpay configuration loaded: YES")
        print("Key ID prefix:", RAZORPAY_KEY_ID[:8])
    else:
        print("Razorpay configuration loaded: NO")
        print("Check .env -> RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET")

    print()

    print("Video Upload:")
    print("Maximum file size: 500 MB")
    print("Allowed: MP4, WebM, OGG, MOV, M4V")

    print()
    print("==========================================")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True,
    )