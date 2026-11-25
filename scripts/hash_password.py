"""Prompt for a dashboard password and print its argon2 hash for ADMIN_PASSWORD_HASH."""
import getpass

from argon2 import PasswordHasher

pw = getpass.getpass("Dashboard password (min 12 chars): ")
if len(pw) < 12:
    raise SystemExit("Use at least 12 characters.")
if pw != getpass.getpass("Again: "):
    raise SystemExit("Passwords differ.")
print(PasswordHasher().hash(pw))
