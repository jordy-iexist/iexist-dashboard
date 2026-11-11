import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.services.monday import client as monday
from app.services.monday.client import MondayServiceError

SETTINGS = SimpleNamespace(
    monday_api_token="test-token",
    monday_api_version="2026-10",
    monday_request_timeout_seconds=5.0,
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


class MondayClientTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(monday, "settings", SETTINGS)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = patch.object(monday.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def test_create_item_sends_token_version_and_variables(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = request.headers
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"data": {"create_item": {"id": 42, "url": "https://x/42"}}})

        item = monday.create_item("123", "Titel", group_id="g1", client=_client(handler))

        self.assertEqual((item.id, item.url), ("42", "https://x/42"))
        self.assertEqual(seen["headers"]["Authorization"], "test-token")
        self.assertEqual(seen["headers"]["API-Version"], "2026-10")
        self.assertEqual(seen["body"]["variables"], {"board": "123", "group": "g1", "name": "Titel"})

    def test_graphql_error_with_http_200_raises(self):
        def handler(request):
            return httpx.Response(200, json={"data": {}, "errors": [
                {"message": "Board not found", "extensions": {"code": "ResourceNotFoundException"}}]})

        with self.assertRaises(MondayServiceError) as ctx:
            monday.create_item("1", "x", client=_client(handler))
        self.assertEqual(ctx.exception.code, "monday_error")
        self.assertIn("Board not found", str(ctx.exception))

    def test_unauthorized_status(self):
        with self.assertRaises(MondayServiceError) as ctx:
            monday.get_board("1", client=_client(lambda r: httpx.Response(401, json={})))
        self.assertEqual(ctx.exception.code, "unauthorized")

    def test_missing_token(self):
        with patch.object(monday, "settings", SimpleNamespace(**{**vars(SETTINGS), "monday_api_token": " "})):
            with self.assertRaises(MondayServiceError) as ctx:
                monday.get_board("1")
        self.assertEqual(ctx.exception.code, "not_configured")

    def test_timeout(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        with self.assertRaises(MondayServiceError) as ctx:
            monday.get_board("1", client=_client(handler))
        self.assertEqual(ctx.exception.code, "timeout")

    def test_retries_after_429_then_succeeds(self):
        calls = []

        def handler(request):
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(429, headers={"Retry-After": "3"}, json={})
            return httpx.Response(200, json={"data": {"create_group": {"id": "g", "title": "T"}}})

        group = monday.create_group("1", "T", client=_client(handler))

        self.assertEqual(group.id, "g")
        self.assertEqual(len(calls), 2)
        self.sleep.assert_called_once_with(3.0)

    def test_gives_up_after_repeated_complexity_errors(self):
        calls = []

        def handler(request):
            calls.append(1)
            return httpx.Response(200, json={"errors": [
                {"message": "budget", "extensions": {"code": "COMPLEXITY_BUDGET_EXHAUSTED"}}]})

        with self.assertRaises(MondayServiceError) as ctx:
            monday.create_group("1", "T", client=_client(handler))
        self.assertEqual(ctx.exception.code, "rate_limited")
        self.assertEqual(len(calls), monday.MAX_ATTEMPTS)

    def test_find_folder_matches_case_insensitive_and_reports_missing(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"folders": [
                {"id": 1, "name": "Anders", "workspace": {"id": 9}},
                {"id": 2, "name": "Website Checklist Scan", "workspace": {"id": 9}},
            ]}})

        folder = monday.find_folder("website checklist scan", client=_client(handler))
        self.assertEqual((folder.id, folder.workspace_id), ("2", "9"))
        with self.assertRaises(MondayServiceError) as ctx:
            monday.find_folder("bestaat niet", client=_client(handler))
        self.assertEqual(ctx.exception.code, "folder_not_found")

    def test_deleted_board_is_not_found(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"boards": [
                {"id": 5, "name": "B", "url": "u", "state": "deleted", "groups": []}]}})

        with self.assertRaises(MondayServiceError) as ctx:
            monday.get_board("5", client=_client(handler))
        self.assertEqual(ctx.exception.code, "board_not_found")

    def test_create_subitem_uses_parent_id(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"data": {"create_subitem": {"id": 7, "url": None}}})

        sub = monday.create_subitem("42", "Pagina /a/", client=_client(handler))

        self.assertEqual((sub.id, sub.url), ("7", None))
        self.assertEqual(seen["body"]["variables"], {"parent": "42", "name": "Pagina /a/"})

    def test_missing_item_ids_reports_deleted_and_unknown(self):
        def handler(request):
            return httpx.Response(200, json={"data": {"items": [
                {"id": "1", "state": "active"},
                {"id": "2", "state": "deleted"},
                {"id": "3", "state": "archived"},
            ]}})

        missing = monday.missing_item_ids(["1", "2", "3", "4"], client=_client(handler))

        self.assertEqual(missing, {"2", "4"})

    def test_parse_board_id(self):
        self.assertEqual(monday.parse_board_id(" 123 "), "123")
        self.assertEqual(monday.parse_board_id("https://x.monday.com/boards/987/views/1"), "987")
        self.assertIsNone(monday.parse_board_id("geen bord"))


if __name__ == "__main__":
    unittest.main()
