"""Keep publication transport regression tests on synthetic, isolated admission evidence."""

import pytest

from tests.publication_admission_fixtures import install_publication_admission


@pytest.fixture(autouse=True)
def publication_admission(monkeypatch, tmp_path):
    return install_publication_admission(monkeypatch, tmp_path)
