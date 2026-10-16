import pytest

from backend.core import config


@pytest.fixture(autouse=True)
def isolated_user_state(monkeypatch, tmp_path_factory):
    """Không test nào được ghi vào data/ thật (danh sách kênh, lựa chọn quét của người dùng)."""
    state = tmp_path_factory.mktemp("user_state")
    monkeypatch.setattr(config, "SETTINGS_FILE", state / "settings.json")
    monkeypatch.setattr(config, "CHANNELS_FILE", state / "channels.txt")
