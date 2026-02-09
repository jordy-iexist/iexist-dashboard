import csv
import io
from typing import Any


def parse_csv(file_content: bytes) -> list[dict[str, Any]]:
    """Parse CSV content and return list of row dictionaries."""
    content = file_content.decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    return [row for row in reader]


def fill_template(template: str, row_data: dict[str, Any]) -> str:
    """Fill template placeholders with row data values."""
    result = template
    for key, value in row_data.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result
