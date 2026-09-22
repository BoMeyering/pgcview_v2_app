from .base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])

DATABASES = {
    "default": env.db("DATABASE_URL", default="postgres://pgcview:pgcview@db:5432/pgcview"),
}

# Cookies only ever travel over HTTPS in production (TLS terminated upstream —
# see SECURE_PROXY_SSL_HEADER in base.py).
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# No transactional email in this app (Google-only auth, ACCOUNT_EMAIL_VERIFICATION
# is "none") — console backend avoids a slow/failing SMTP attempt if anything
# ever does call send_mail.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
