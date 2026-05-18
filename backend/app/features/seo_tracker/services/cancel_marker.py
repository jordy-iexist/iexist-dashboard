SCAN_CANCELED_ERROR_MARKER = "[scan_canceled_by_user]"
DEFAULT_SCAN_CANCELED_MESSAGE = "Scan geannuleerd door gebruiker."


def build_scan_canceled_error_message(
    message: str = DEFAULT_SCAN_CANCELED_MESSAGE,
) -> str:
    normalized = str(message or "").strip() or DEFAULT_SCAN_CANCELED_MESSAGE
    return f"{SCAN_CANCELED_ERROR_MARKER} {normalized}"


def is_scan_canceled_error_message(value: object) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().startswith(SCAN_CANCELED_ERROR_MARKER)


def strip_scan_canceled_error_marker(value: object) -> str | None:
    if value in {None, ""}:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    if raw.startswith(SCAN_CANCELED_ERROR_MARKER):
        stripped = raw[len(SCAN_CANCELED_ERROR_MARKER) :].strip(" :-")
        return stripped or DEFAULT_SCAN_CANCELED_MESSAGE

    return raw
