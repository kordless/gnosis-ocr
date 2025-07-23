import pytest

from app.config import format_file_size


@pytest.mark.parametrize(
    "size,expected",
    [
        (500, "500.00 B"),
        (1023, "1023.00 B"),
        (1024, "1.00 KB"),
        (1536, "1.50 KB"),
        (1024 ** 2, "1.00 MB"),
        (10 * 1024 ** 2, "10.00 MB"),
        (1024 ** 3, "1.00 GB"),
        (1024 ** 4, "1.00 TB"),
    ],
)
def test_format_file_size(size: int, expected: str) -> None:
    assert format_file_size(size) == expected
