from __future__ import annotations

import pytest

from app.services.upload_asset_service import (
    UploadAssetError,
    delete_upload_assets,
    list_upload_assets,
)


def test_upload_asset_list_and_delete(tmp_path) -> None:
    upload_dir = tmp_path / 'assets' / 'uploads'
    upload_dir.mkdir(parents=True)
    (upload_dir / 'one.png').write_bytes(b'png')
    (upload_dir / 'two.pdf').write_bytes(b'pdf')

    items = list_upload_assets(tmp_path)
    assert {item['filename'] for item in items} == {'one.png', 'two.pdf'}

    deleted = delete_upload_assets(tmp_path, ['one.png', 'two.pdf'])
    assert deleted == 2
    assert list(items) and list_upload_assets(tmp_path) == []


def test_upload_asset_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(UploadAssetError):
        delete_upload_assets(tmp_path, ['../secret.txt'])
