from types import SimpleNamespace
import pytest
from backend.core import keys, applog


def test_masking():
    assert keys.mask(None) == ''
    assert keys.mask(' short ') == '••••'
    assert keys.mask('long-key-1234') == '••••1234'


def test_isolated_secure_storage(monkeypatch):
    vault = type('WinVaultKeyring', (), {'__module__': 'keyring.backends.Windows'})()
    values = {}
    kr = SimpleNamespace(get_keyring=lambda: vault,
        get_password=lambda service, name: values.get((service, name)),
        set_password=lambda service, name, value: values.update({(service, name): value}),
        delete_password=lambda service, name: values.pop((service, name)))
    monkeypatch.setattr(keys, '_keyring', lambda: kr)
    assert keys.storage_secure()
    keys.set_key('llm', ' test-credential-1234 ')
    assert values == {('VideoCongThucPublic', 'llm'): 'test-credential-1234'}
    assert keys.get_key() == 'test-credential-1234'
    assert 'test-credential-1234' not in applog.redact('test-credential-1234')
    keys.delete_key()
    keys.delete_key()
    assert not values
    with pytest.raises(ValueError):
        keys.get_key('jev')


def test_insecure_storage_never_writes(monkeypatch):
    kr = SimpleNamespace(get_keyring=lambda: object(), set_password=lambda *args: pytest.fail('insecure write'))
    monkeypatch.setattr(keys, '_keyring', lambda: kr)
    assert not keys.storage_secure()
    with pytest.raises(RuntimeError, match='Credential Manager'):
        keys.set_key('llm', 'credential')


def test_unavailable_read(monkeypatch):
    def unavailable():
        raise RuntimeError('vault unavailable')
    monkeypatch.setattr(keys, '_keyring', unavailable)
    assert keys.get_key() is None and not keys.storage_secure()
