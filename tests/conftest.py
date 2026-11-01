import pytest

from housing.service import HousingService


@pytest.fixture
def service(tmp_path):
    return HousingService(tmp_path / "housing.sqlite3")
