"""Tests for the OpenAI tools adapter layer.

Verifies that Pipecat FunctionSchema tools are correctly converted to
OpenAI format and that handlers are properly wrapped as async functions
that return strings.
"""

from __future__ import annotations

import asyncio
import json
import unittest

from agents.hapax_daimonion.tools_openai import (
    _FakeParams,
    _make_async_wrapper,
    _schema_to_openai,
    get_openai_tools,
)


class TestSchemaConversion(unittest.TestCase):
    """Test _schema_to_openai preserves schema structure."""

    def test_required_fields_from_schema_level(self):
        """Required list comes from schema.required, not per-property."""
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        schema = FunctionSchema(
            name="test_tool",
            description="A test tool",
            properties={
                "query": {"type": "string", "description": "search query"},
                "limit": {"type": "integer", "description": "max results"},
            },
            required=["query"],
        )
        result = _schema_to_openai(schema)
        params = result["function"]["parameters"]
        self.assertEqual(params["required"], ["query"])
        self.assertIn("query", params["properties"])
        self.assertIn("limit", params["properties"])

    def test_empty_required(self):
        """Tools with no required fields get empty list."""
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        schema = FunctionSchema(
            name="no_args",
            description="No arguments",
            properties={},
            required=[],
        )
        result = _schema_to_openai(schema)
        self.assertEqual(result["function"]["parameters"]["required"], [])

    def test_enum_values_preserved(self):
        """Enum values in properties are passed through."""
        from pipecat.adapters.schemas.function_schema import FunctionSchema

        schema = FunctionSchema(
            name="filter_tool",
            description="Filter",
            properties={
                "source": {
                    "type": "string",
                    "enum": ["gmail", "gdrive", "youtube"],
                    "description": "source filter",
                },
            },
            required=[],
        )
        result = _schema_to_openai(schema)
        source_prop = result["function"]["parameters"]["properties"]["source"]
        self.assertEqual(source_prop["enum"], ["gmail", "gdrive", "youtube"])


class TestFakeParams(unittest.TestCase):
    """Test _FakeParams shim handles both str and dict results."""

    def test_string_result(self):
        params = _FakeParams(arguments={"q": "test"})
        asyncio.run(params.result_callback("hello world"))
        self.assertEqual(params._result, "hello world")

    def test_dict_result_serialized(self):
        params = _FakeParams(arguments={})
        asyncio.run(params.result_callback({"status": "ok", "count": 5}))
        self.assertIsInstance(params._result, str)
        parsed = json.loads(params._result)
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(parsed["count"], 5)

    def test_list_result_serialized(self):
        params = _FakeParams(arguments={})
        asyncio.run(params.result_callback([1, 2, 3]))
        self.assertIsInstance(params._result, str)
        self.assertEqual(json.loads(params._result), [1, 2, 3])


class TestHandlerWrapping(unittest.TestCase):
    """Test that handler wrapping produces proper async functions."""

    def test_make_async_wrapper_is_coroutine_function(self):
        async def dummy_handler(params):
            await params.result_callback("dummy result")

        wrapper = _make_async_wrapper(dummy_handler)
        self.assertTrue(asyncio.iscoroutinefunction(wrapper))

    def test_wrapped_handler_returns_string(self):
        async def dummy_handler(params):
            await params.result_callback("hello")

        wrapper = _make_async_wrapper(dummy_handler)
        result = asyncio.run(wrapper({"arg": "val"}))
        self.assertEqual(result, "hello")

    def test_wrapped_handler_dict_result_returns_json_string(self):
        async def dict_handler(params):
            await params.result_callback({"status": "sent", "id": "abc"})

        wrapper = _make_async_wrapper(dict_handler)
        result = asyncio.run(wrapper({}))
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "sent")

    def test_wrapped_handler_exception_returns_error_json(self):
        async def failing_handler(params):
            raise ValueError("something broke")

        wrapper = _make_async_wrapper(failing_handler)
        result = asyncio.run(wrapper({}))
        parsed = json.loads(result)
        self.assertIn("error", parsed)
        self.assertIn("something broke", parsed["error"])

    def test_wrapped_handler_no_callback_returns_done(self):
        async def silent_handler(params):
            pass  # Never calls result_callback

        wrapper = _make_async_wrapper(silent_handler)
        result = asyncio.run(wrapper({}))
        self.assertEqual(result, "Done.")


class TestGetOpenaiTools(unittest.TestCase):
    """Test get_openai_tools returns correct structure."""

    def test_guest_mode_returns_empty(self):
        tools, handlers = get_openai_tools(guest_mode=True)
        self.assertEqual(tools, [])
        self.assertEqual(handlers, {})

    def test_returns_tools_and_handlers(self):
        tools, handlers = get_openai_tools()
        self.assertGreaterEqual(len(tools), 20)
        self.assertEqual(len(tools), len(handlers))

    def test_all_handlers_are_async(self):
        _, handlers = get_openai_tools()
        for name, handler in handlers.items():
            self.assertTrue(
                asyncio.iscoroutinefunction(handler),
                f"Handler '{name}' is not a coroutine function",
            )

    def test_all_tools_have_required_structure(self):
        tools, _ = get_openai_tools()
        for tool in tools:
            self.assertEqual(tool["type"], "function")
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])
            params = tool["function"]["parameters"]
            self.assertEqual(params["type"], "object")
            self.assertIn("properties", params)
            self.assertIn("required", params)

    def test_search_documents_required_query(self):
        tools, _ = get_openai_tools()
        search = next(t for t in tools if t["function"]["name"] == "search_documents")
        self.assertIn("query", search["function"]["parameters"]["required"])

    def test_send_sms_required_fields(self):
        tools, _ = get_openai_tools()
        sms = next(t for t in tools if t["function"]["name"] == "send_sms")
        required = sms["function"]["parameters"]["required"]
        self.assertIn("recipient", required)
        self.assertIn("message", required)

    def test_source_filter_includes_youtube(self):
        tools, _ = get_openai_tools()
        search = next(t for t in tools if t["function"]["name"] == "search_documents")
        enum = search["function"]["parameters"]["properties"]["source_filter"]["enum"]
        self.assertIn("youtube", enum)
        self.assertIn("weather", enum)
        self.assertIn("health_connect", enum)

    def test_new_utility_tools_present(self):
        _, handlers = get_openai_tools()
        self.assertIn("get_current_time", handlers)
        self.assertIn("get_weather", handlers)
        self.assertIn("get_briefing", handlers)

    def test_consent_tools_present(self):
        _, handlers = get_openai_tools()
        self.assertIn("check_consent_status", handlers)
        self.assertIn("describe_consent_flow", handlers)
        self.assertIn("check_governance_health", handlers)


class TestUtilityHandlers(unittest.TestCase):
    """Test the new utility tool handlers."""

    def test_get_current_time_returns_formatted_string(self):
        from agents.hapax_daimonion.tools import handle_get_current_time

        async def run():
            params = _FakeParams(arguments={})
            await handle_get_current_time(params)
            return params._result

        result = asyncio.run(run())
        self.assertIsInstance(result, str)
        # Should contain day of week and time
        self.assertTrue(
            any(
                day in result
                for day in [
                    "Monday",
                    "Tuesday",
                    "Wednesday",
                    "Thursday",
                    "Friday",
                    "Saturday",
                    "Sunday",
                ]
            )
        )


if __name__ == "__main__":
    unittest.main()
