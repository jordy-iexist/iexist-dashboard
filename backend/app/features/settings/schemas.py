from pydantic import BaseModel


class OpenAISettingsResponse(BaseModel):
    has_personal_openai_api_key: bool


class OpenAISettingsUpdateRequest(BaseModel):
    openai_api_key: str | None = None
