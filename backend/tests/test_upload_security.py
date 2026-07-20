"""上传安全校验单测。"""

from app.core.upload_security import validate_upload


def test_upload_rejects_executable():
    ok, err = validate_upload(filename="evil.exe", data=b"MZ", allowed_suffixes={".pdf"})
    assert not ok
    assert err


def test_upload_accepts_small_pdf():
    ok, err = validate_upload(
        filename="guide.pdf",
        data=b"%PDF-1.4 test",
        allowed_suffixes={".pdf"},
    )
    assert ok
    assert err is None
