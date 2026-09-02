import uuid

import jwt as pyjwt
import pytest

from app.auth.jwt import create_access_token, decode_access_token
from app.config import settings


def test_roundtrip():
    user_id = uuid.uuid4()
    token = create_access_token(user_id)
    assert decode_access_token(token) == user_id


def test_token_expirado(monkeypatch):
    monkeypatch.setattr(settings, "jwt_ttl_hours", -1)
    token = create_access_token(uuid.uuid4())
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_access_token(token)


def test_token_adulterado():
    token = create_access_token(uuid.uuid4())
    with pytest.raises(pyjwt.PyJWTError):
        decode_access_token(token[:-2] + "xx")
