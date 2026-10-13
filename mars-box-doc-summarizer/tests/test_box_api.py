import json

import pytest

from box_doc_summarizer import box_api
from box_doc_summarizer.box_api import BoxError, RestBoxClient, file_url, load_jwt_config


def _cfg(passphrase=None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode())
        if passphrase
        else serialization.NoEncryption()
    )
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc).decode()
    return {
        "boxAppSettings": {
            "clientID": "cid",
            "clientSecret": "csecret",
            "appAuth": {"publicKeyID": "kid1", "privateKey": pem, "passphrase": passphrase or ""},
        },
        "enterpriseID": "42",
    }, key


class _Resp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code, self._body, self.content = status, body or {}, content

    def json(self):
        return self._body


class _Session:
    def __init__(self):
        self.calls = []

    def post(self, url, data=None, timeout=None):
        self.calls.append(("POST", url, data))
        return _Resp(body={"access_token": "tok", "expires_in": 3600})

    def request(self, method, url, headers=None, timeout=None, **kw):
        self.calls.append((method, url, kw))
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/folders/1/items"):
            return _Resp(body={"total_count": 3, "entries": [
                {"type": "file", "id": "10", "name": "a.md", "size": 5, "shared_link": {"url": "https://app.box.com/s/abc"}},
                {"type": "folder", "id": "2", "name": "sub"},
                {"type": "web_link", "id": "99", "name": "x"},
            ]})
        if url.endswith("/folders/2/items"):
            return _Resp(body={"total_count": 1, "entries": [{"type": "file", "id": "11", "name": "b.pdf", "size": 9}]})
        if url.endswith("/folders/1"):
            return _Resp(body={"id": "1", "name": "Trip"})
        if url.endswith("/files/10/content") and method == "GET":
            return _Resp(content=b"hello")
        if "upload.box.com" in url:
            return _Resp(body={"entries": [{"id": "500"}]})
        return _Resp(status=404, body={"message": "not found"})


def test_jwt_assertion_and_listing():
    cfg, key = _cfg(passphrase="pw")
    sess = _Session()
    c = RestBoxClient(cfg, session=sess)
    assert c.get_folder("1").name == "Trip"
    files = c.list_files("1")
    assert [(f.path, f.url) for f in files] == [
        ("a.md", "https://app.box.com/s/abc"),
        ("sub/b.pdf", "https://app.box.com/file/11"),
    ]
    assert c.download("10") == b"hello"
    import jwt

    assertion = sess.calls[0][2]["assertion"]
    claims = jwt.decode(assertion, key.public_key(), algorithms=["RS256"], audience=box_api.TOKEN_URL)
    assert claims["iss"] == "cid" and claims["sub"] == "42" and claims["box_sub_type"] == "enterprise"
    assert jwt.get_unverified_header(assertion)["kid"] == "kid1"


def test_upload_new_vs_version():
    cfg, _ = _cfg()
    sess = _Session()
    c = RestBoxClient(cfg, session=sess)
    c.upload_text("1", "EXECUTIVE-SUMMARY.md", "# hi")
    c.upload_text("1", "EXECUTIVE-SUMMARY.md", "# hi", existing_file_id="500")
    urls = [u for m, u, _ in sess.calls if m == "POST" and "upload" in u]
    assert urls[0].endswith("/files/content") and urls[1].endswith("/files/500/content")
    attrs = json.loads([kw for m, u, kw in sess.calls if m == "POST" and "upload" in u][0]["data"]["attributes"])
    assert attrs["parent"]["id"] == "1"


def test_config_validation():
    with pytest.raises(BoxError):
        load_jwt_config("")
    with pytest.raises(BoxError, match="enterpriseID"):
        load_jwt_config(json.dumps({"boxAppSettings": {"clientID": "a", "clientSecret": "b", "appAuth": {"publicKeyID": "c", "privateKey": "d"}}}))
    assert file_url("5") == "https://app.box.com/file/5"


def test_errors_do_not_leak_secrets():
    cfg, _ = _cfg()
    c = RestBoxClient(cfg, session=_Session())
    with pytest.raises(BoxError) as ei:
        c.download("404")
    assert "csecret" not in str(ei.value) and "PRIVATE KEY" not in str(ei.value)
