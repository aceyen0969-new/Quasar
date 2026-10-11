import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import ai.provider_router as router


class TestProviderRouter(unittest.TestCase):

    def run_async(self, coroutine):
        return asyncio.run(coroutine)

    def test_first_provider_succeeds(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    return_value='{"ok": true}',
                ) as groq,
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                ) as gemini,
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Groq", '{"ok": true}'),
                )
                groq.assert_awaited_once_with("test")
                gemini.assert_not_awaited()
                success.assert_called_once_with("Groq")
                failure.assert_not_called()

        self.run_async(scenario())

    def test_falls_back_after_provider_exception(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("simulated failure"),
                ),
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    return_value='{"ok": true}',
                ) as gemini,
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Gemini", '{"ok": true}'),
                )
                gemini.assert_awaited_once_with("test")
                failure.assert_called_once_with("Groq", 30)
                success.assert_called_once_with("Gemini")

        self.run_async(scenario())

    def test_falls_back_after_invalid_json(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    return_value="not valid JSON",
                ),
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    return_value='{"fallback": true}',
                ),
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Gemini", '{"fallback": true}'),
                )
                failure.assert_called_once_with("Groq", 30)
                success.assert_called_once_with("Gemini")

        self.run_async(scenario())

    def test_falls_back_after_empty_response(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    return_value="",
                ),
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    return_value='{"fallback": true}',
                ),
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Gemini", '{"fallback": true}'),
                )
                failure.assert_called_once_with("Groq", 30)
                success.assert_called_once_with("Gemini")

        self.run_async(scenario())

    def test_falls_back_after_timeout(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    side_effect=asyncio.TimeoutError,
                ),
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    return_value='{"fallback": true}',
                ) as gemini,
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Gemini", '{"fallback": true}'),
                )
                gemini.assert_awaited_once_with("test")
                failure.assert_called_once_with("Groq", 30)
                success.assert_called_once_with("Gemini")

        self.run_async(scenario())

    def test_skips_provider_in_cooldown(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                ) as groq,
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    return_value='{"fallback": true}',
                ) as gemini,
                patch.object(
                    router,
                    "is_available",
                    side_effect=lambda name: name != "Groq",
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(
                    result,
                    ("Gemini", '{"fallback": true}'),
                )
                groq.assert_not_awaited()
                gemini.assert_awaited_once_with("test")
                success.assert_called_once_with("Gemini")
                failure.assert_not_called()

        self.run_async(scenario())

    def test_all_providers_fail(self):
        async def scenario():
            with (
                patch.object(
                    router,
                    "ask_groq_json",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("simulated failure"),
                ),
                patch.object(
                    router,
                    "ask_gemini_json",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("simulated failure"),
                ),
                patch.object(
                    router,
                    "ask_claude_json",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("simulated failure"),
                ),
                patch.object(
                    router,
                    "ask_openrouter_json",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("simulated failure"),
                ),
                patch.object(
                    router,
                    "is_available",
                    return_value=True,
                ),
                patch.object(router, "mark_success") as success,
                patch.object(router, "mark_failure") as failure,
            ):
                result = await router.ask_with_fallback("test")

                self.assertEqual(result, (None, None))
                self.assertEqual(failure.call_count, 4)
                success.assert_not_called()

        self.run_async(scenario())


if __name__ == "__main__":
    unittest.main()
