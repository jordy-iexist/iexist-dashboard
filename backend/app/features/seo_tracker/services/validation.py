def normalize_keyword(raw_keyword: str) -> str:
    normalized = " ".join(str(raw_keyword or "").split())
    if not normalized:
        raise ValueError("Keyword is verplicht.")
    if len(normalized) < 2:
        raise ValueError("Keyword moet minimaal 2 tekens bevatten.")
    if len(normalized) > 120:
        raise ValueError("Keyword mag maximaal 120 tekens bevatten.")
    return normalized
