import asyncio
import json

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


async def ask_with_fallback(prompt: str):
    for provider_name, function_name, timeout in PROVIDERS:
        if not is_available(provider_name):
            print(
                f"AI PROVIDER: Skipping {provider_name} "
                f"because it is in cooldown."
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
            print(
                f"AI PROVIDER: {provider_name} failed."
            )
            print(repr(error))

            mark_failure(
                provider_name,
                PROVIDER_COOLDOWN,
            )

    print("AI PROVIDER: All providers failed.")

    return None, None