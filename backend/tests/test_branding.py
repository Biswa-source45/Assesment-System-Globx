from app.core.config import Settings
from app.core.security import totp_uri


def test_the_product_is_called_aptivon():
    # the built-in defaults (a server's own .env may override them)
    assert Settings.model_fields["app_name"].default == "APTIVON"
    assert Settings.model_fields["smtp_from"].default.startswith("APTIVON <")
    assert "issuer=APTIVON" in totp_uri("JBSWY3DPEHPK3PXP", "a@b.co")
