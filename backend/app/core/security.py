from pwdlib import PasswordHash


# Argon2 password hashing
password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password securely."""
    return password_hasher.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Verify a plaintext password against its stored hash."""
    return password_hasher.verify(
        plain_password,
        hashed_password,
    )


def verify_password_and_update(
    plain_password: str,
    hashed_password: str,
) -> tuple[bool, str | None]:
    """Verify a password and return an updated hash if needed."""
    return password_hasher.verify_and_update(
        plain_password,
        hashed_password,
    )