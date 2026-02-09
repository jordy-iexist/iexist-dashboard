from openai import OpenAI

from app.config import settings

client = OpenAI(api_key=settings.openai_api_key)


def generate_blog(prompt: str) -> str:
    """Generate blog content using OpenAI API."""
    response = client.chat.completions.create(
        model="gpt-5.2",
        messages=[
            {
                "role": "system",
                "content": (
                    "Je bent een professionele blog schrijver. "
                    "Schrijf informatieve, goed gestructureerde blogs in het Nederlands."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
    )
    return response.choices[0].message.content or ""
