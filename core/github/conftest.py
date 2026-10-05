import hashlib
import hmac
import json

import pytest
from cryptography.fernet import Fernet

SECRET = b"test-secret"


@pytest.fixture
def gh(settings):
    """GitHub 설정이 켜진 상태. 실제 GitHub는 부르지 않는다."""
    settings.GITHUB_ENABLED = True
    settings.GITHUB_WEBHOOK_SECRET = SECRET.decode()
    settings.CREDENTIAL_KEY = Fernet.generate_key().decode()
    settings.GITHUB_APP_ID = "1"
    settings.GITHUB_APP_SLUG = "udally-test"
    settings.GITHUB_CLIENT_ID = "Iv1.test"
    settings.GITHUB_CLIENT_SECRET = "client-secret"
    return settings


def signed(client, payload: dict, event: str, delivery: str = "d-1", secret: bytes = SECRET):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return client.post(
        "/api/integrations/github/webhook",
        body,
        content_type="application/json",
        headers={
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": event,
            "X-GitHub-Delivery": delivery,
        },
    )
