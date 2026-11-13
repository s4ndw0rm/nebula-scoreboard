"""Flag derivation shared by the scoreboard scripts.

Must match nebula-agent (agent.c):
    NEBULA{<slug>_<hex>}  with  hex = HMAC-SHA256(key, lower(login) + ":" + challenge_id)[:6 bytes]
"""
import hashlib
import hmac


def derive_flag(key: bytes, login: str, challenge_id: str, slug: str) -> str:
    msg = f"{login.lower()}:{challenge_id}".encode()
    mac = hmac.new(key, msg, hashlib.sha256).digest()
    return f"NEBULA{{{slug}_{mac[:6].hex()}}}"


def check_flag(key: bytes, login: str, challenge_id: str, slug: str, flag: str) -> bool:
    return hmac.compare_digest(derive_flag(key, login, challenge_id, slug), flag.strip())


def player_id(key: bytes, login: str) -> str:
    """Stable, non-reversible id used in public data instead of the login."""
    return hmac.new(key, f"pid:{login.lower()}".encode(), hashlib.sha256).hexdigest()[:12]
