from app.auth.passwords import hash_password, verify_password


def test_hash_e_verificacao():
    h = hash_password("s3nh4-forte")
    assert h != "s3nh4-forte"
    assert verify_password("s3nh4-forte", h)
    assert not verify_password("errada", h)


def test_hashes_diferentes_por_salt():
    assert hash_password("x" * 10) != hash_password("x" * 10)
