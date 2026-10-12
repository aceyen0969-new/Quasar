
import asyncio
import json
import re

from ai.providers import (
    ask_groq_json,
    ask_gemini_json,
    ask_claude_json,
    ask_openrouter_json,
)

from ai.health import (
    mark_success,
    mark_failure,
    is_available,
)


PROVIDERS = [
    ("Groq", "ask_groq_json", 10),
    ("Gemini", "ask_gemini_json", 8),
    ("Claude", "ask_claude_json", 10),
    ("OpenRouter", "ask_openrouter_json", 10),
]

PROVIDER_COOLDOWN = 30


def extract_retry_seconds(error_text):
    patterns = [
        r"""retryDelay["']?\s*:\s*["']?(\d+(?:\.\d+)?)\s*s""",
        r"""retry\s+(?:in|after)\s+(\d+)\s*(?:seconds?|secs?|s)\b""",
        r"""retry[-_\s]?after\s*[:=]\s*["']?(\d+)""",
    ]

    for pattern in patterns:
        match = re.search(pattern, error_text, re.IGNORECASE)

        if match:
            seconds = int(float(match.group(1)))

            if seconds > 0:
                return seconds

    return None


async def ask_with_fallback(prompt: str):
    for provider_name, function_name, timeout in PROVIDERS:
        if not is_available(provider_name):
            print(
                f"AI PROVIDER: Skipping {provider_name} "
                "because it is in cooldown."
            )
            continue

        provider_function = globals()[function_name]

        print(
            f"AI PROVIDER: Trying {provider_name} "
            f"(timeout: {timeout}s)..."
        )

        try:
            result = await asyncio.wait_for(
                provider_function(prompt),
                timeout=timeout,
            )

            if not result or not isinstance(result, str):
                print(
                    f"AI PROVIDER: {provider_name} "
                    "returned an empty or invalid response."
                )
                mark_failure(
                    provider_name,
                    PROVIDER_COOLDOWN,
                )
                continue

            try:
                json.loads(result)

            except (json.JSONDecodeError, TypeError):
                print(
                    f"AI PROVIDER: {provider_name} "
                    "returned invalid JSON."
                )
                mark_failure(
                    provider_name,
                    PROVIDER_COOLDOWN,
                )
                continue

            mark_success(provider_name)

            print(
                f"AI PROVIDER: {provider_name} succeeded."
            )

            return provider_name, result

        except asyncio.TimeoutError:
            print(
                f"AI PROVIDER: {provider_name} "
                f"timed out after {timeout}s."
            )
            mark_failure(
                provider_name,
                PROVIDER_COOLDOWN,
            )

        except Exception as error:
            error_text = str(error)
            retry_seconds = extract_retry_seconds(error_text)

            cooldown = (
                retry_seconds
                if retry_seconds is not None
                else PROVIDER_COOLDOWN
            )

            print(
                f"AI PROVIDER: {provider_name} failed."
            )
            print(error_text)
            print(
                f"AI PROVIDER: {provider_name} cooldown "
                f"set to {cooldown}s."
            )

            mark_failure(provider_name, cooldown)

    print("AI PROVIDER: All providers failed.")

    return None, None
