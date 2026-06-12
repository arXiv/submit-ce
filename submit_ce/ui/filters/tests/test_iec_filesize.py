import pytest

from .. import iec_filesize


@pytest.mark.parametrize("bytes_, expected", [
    (0, "0B"),
    (1, "1.00 B"),
    (1023, "1023.00 B"),
    (1024, "1.00 KiB"),
    (1536, "1.50 KiB"),
    (50 * 1024, "50.00 KiB"),
    (1024 ** 2, "1.00 MiB"),
    (5 * 1024 ** 2, "5.00 MiB"),
    (1024 ** 3, "1.00 GiB"),
    (1024 ** 4, "1.00 TiB"),
    (1024 ** 5, "1024.00 TiB"),  # caps at the largest unit
    (1500.5, "1.47 KiB"),        # float input
])
def test_iec_filesize(bytes_, expected):
    assert iec_filesize(bytes_) == expected
