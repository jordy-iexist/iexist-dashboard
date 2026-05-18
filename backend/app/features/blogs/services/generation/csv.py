import csv
import io
import re
from typing import Any

DEFAULT_PROMPT_TEMPLATE = (
    "Schrijf een blog van {woorden} woorden voor klant {klant}. "
    "Gebruik ankertekst '{anker_1}' met URL '{anker_1_url}' en "
    "ankertekst '{anker_2}' met URL '{anker_2_url}'. "
    "Noem '{klant}' minimaal 4 keer op natuurlijke wijze. "
    "Voeg titel en tussenkoppen toe, zonder onnodige hoofdletters."
)
IMAGE_GENERATION_META_FIELD = "__generate_image"

_IMAGE_GENERATION_TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "ja",
    "j",
    "on",
    "aan",
    "x",
}

_IMAGE_GENERATION_FALSE_VALUES = {
    "",
    "0",
    "false",
    "no",
    "n",
    "nee",
    "off",
    "uit",
    "null",
    "none",
    "nil",
    "n/a",
    "na",
    "-",
}

_TEMPLATE_PLACEHOLDER_REGEX = re.compile(r"\{([^{}]*)\}")


def parse_csv(file_content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    content = file_content.decode("utf-8-sig")
    if not content.strip():
        return [], []

    stream = io.StringIO(content)
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(content[:4096], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        pass

    reader = csv.reader(stream, delimiter=delimiter)
    try:
        header_row = next(reader)
    except StopIteration:
        return [], []

    raw_headers = [str(header or "").strip().lstrip("\ufeff") for header in header_row]
    if not raw_headers:
        return [], []

    non_empty_header_indexes = [index for index, header in enumerate(raw_headers) if header]
    headers = [raw_headers[index] for index in non_empty_header_indexes]
    empty_header_indexes = [index for index, header in enumerate(raw_headers) if not header]

    if not headers:
        raise ValueError("CSV header bevat geen geldige kolomnamen.")

    counts: dict[str, int] = {}
    for header in headers:
        counts[header] = counts.get(header, 0) + 1
    duplicate_headers = sorted(header for header, count in counts.items() if count > 1)
    if duplicate_headers:
        duplicates = ", ".join(duplicate_headers)
        raise ValueError(f"CSV bevat dubbele kolomnamen: {duplicates}.")

    rows: list[dict[str, Any]] = []
    for row_index, raw_values in enumerate(reader, start=2):
        if len(raw_values) < len(raw_headers):
            raw_values = raw_values + [""] * (len(raw_headers) - len(raw_values))

        if len(raw_values) > len(raw_headers):
            extra_values = [value.strip() for value in raw_values[len(raw_headers):]]
            if any(extra_values):
                raise ValueError(
                    f"CSV rij {row_index} bevat extra waarden zonder kolomnaam."
                )

        unnamed_values = [
            str(raw_values[index] or "").strip()
            for index in empty_header_indexes
            if index < len(raw_values)
        ]
        if any(unnamed_values):
            raise ValueError(
                f"CSV bevat data in lege kolomkop op rij {row_index}."
            )

        row = {
            header: str(raw_values[index] or "").strip()
            for index, header in zip(non_empty_header_indexes, headers)
        }
        if any(value for value in row.values()):
            rows.append(row)

    return headers, rows


def normalize_prompt_template(template: str | None) -> str:
    normalized = str(template or "").strip()
    return normalized if normalized else DEFAULT_PROMPT_TEMPLATE


def extract_template_placeholders(template: str) -> list[str]:
    if template.count("{") != template.count("}"):
        raise ValueError(
            "Prompt bevat ongeldige accolades. Controleer of elke '{' een '}' heeft."
        )

    placeholders: list[str] = []
    seen: set[str] = set()
    for match in _TEMPLATE_PLACEHOLDER_REGEX.finditer(template):
        placeholder = match.group(1).strip()
        if not placeholder:
            raise ValueError("Lege placeholder gevonden. Gebruik bijvoorbeeld {klant}.")
        if placeholder in seen:
            continue
        placeholders.append(placeholder)
        seen.add(placeholder)

    return placeholders


def normalize_mapping(mapping: dict[str, Any], required_fields: list[str]) -> dict[str, str]:
    return {
        field: str(mapping.get(field, "") or "").strip()
        for field in required_fields
    }


def validate_mapping(
    mapping: dict[str, str], headers: list[str], required_fields: list[str]
) -> None:
    if not required_fields:
        raise ValueError(
            "Prompt moet minimaal één placeholder bevatten, bijvoorbeeld {klant}."
        )

    missing_fields = [field for field in required_fields if not mapping.get(field)]
    if missing_fields:
        missing = ", ".join(missing_fields)
        raise ValueError(f"Ontbrekende verplichte mappings: {missing}.")

    header_set = set(headers)
    unknown_columns = [
        f"{field} -> {mapping[field]}"
        for field in required_fields
        if mapping[field] not in header_set
    ]
    if unknown_columns:
        unknown = ", ".join(unknown_columns)
        raise ValueError(f"Gekoppelde kolommen bestaan niet in CSV-header: {unknown}.")


def map_row_to_prompt_fields(
    row: dict[str, Any], mapping: dict[str, str], required_fields: list[str]
) -> dict[str, str]:
    return {
        field: str(row.get(mapping[field], "") or "").strip()
        for field in required_fields
    }


def get_missing_prompt_values(
    prompt_row: dict[str, Any], required_fields: list[str]
) -> list[str]:
    return [
        field
        for field in required_fields
        if not str(prompt_row.get(field, "") or "").strip()
    ]


def build_blog_prompt(template: str, prompt_row: dict[str, Any]) -> str:
    placeholders = extract_template_placeholders(template)
    if not placeholders:
        raise ValueError(
            "Prompt moet minimaal één placeholder bevatten, bijvoorbeeld {klant}."
        )

    def replace_placeholder(match: re.Match[str]) -> str:
        placeholder = match.group(1).strip()
        if not placeholder:
            raise ValueError("Lege placeholder gevonden. Gebruik bijvoorbeeld {klant}.")

        value = str(prompt_row.get(placeholder, "") or "").strip()
        if not value:
            raise ValueError(f"Waarde ontbreekt voor placeholder: {placeholder}.")
        return value

    return _TEMPLATE_PLACEHOLDER_REGEX.sub(replace_placeholder, template)


def parse_image_generation_cell(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    normalized = str(value).strip().lower()
    if normalized in _IMAGE_GENERATION_TRUE_VALUES:
        return True

    if normalized in _IMAGE_GENERATION_FALSE_VALUES:
        return False

    return False


def should_generate_image_from_row_data(
    row_data: dict[str, Any] | None,
    *,
    default_when_missing: bool = False,
) -> bool:
    if not isinstance(row_data, dict):
        return default_when_missing

    if IMAGE_GENERATION_META_FIELD not in row_data:
        return default_when_missing

    return parse_image_generation_cell(row_data.get(IMAGE_GENERATION_META_FIELD))
