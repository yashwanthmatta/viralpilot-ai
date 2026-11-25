"""Print fresh SECRET_KEY and CREDENTIALS_KEY values (paste into your host's secret env vars)."""
import secrets

from cryptography.fernet import Fernet

print(f"SECRET_KEY={secrets.token_urlsafe(48)}")
print(f"CREDENTIALS_KEY={Fernet.generate_key().decode()}")
