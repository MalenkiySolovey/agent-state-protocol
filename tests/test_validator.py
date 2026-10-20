from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from validate import example_property_names, property_name_is_forbidden, schema_property_names, semantic_error_keywords  # noqa: E402


class ValidatorPrivacyTests(unittest.TestCase):
    def test_secret_field_spellings_are_rejected(self) -> None:
        for field_name in ("accessToken", "access_token", "apiKey", "api_key", "totpSecret", "authJson"):
            with self.subTest(field_name=field_name):
                self.assertTrue(property_name_is_forbidden(field_name))

    def test_secret_references_and_opaque_ids_remain_allowed(self) -> None:
        for field_name in ("secretId", "credentialId", "ownerId", "revision"):
            with self.subTest(field_name=field_name):
                self.assertFalse(property_name_is_forbidden(field_name))

    def test_scans_explicit_schema_and_nested_example_properties(self) -> None:
        schema = {"properties": {"payload": {"properties": {"refreshToken": {"type": "string"}}}}}
        example = {"credential": {"api_key": "must-not-be-published"}}
        self.assertIn("refreshToken", set(schema_property_names(schema)))
        self.assertIn("api_key", set(example_property_names(example)))
        self.assertTrue(any(property_name_is_forbidden(name) for name in schema_property_names(schema)))
        self.assertTrue(any(property_name_is_forbidden(name) for name in example_property_names(example)))

    def test_new_account_collections_reject_duplicate_account_ids_semantically(self) -> None:
        source_collection = {
            "schemaVersion": 1,
            "accounts": [
                {"accountId": "synthetic-duplicate"},
                {"accountId": "synthetic-duplicate"},
            ],
        }
        nickname_collection = {
            "schemaVersion": 1,
            "accounts": [
                {"accountId": "synthetic-duplicate"},
                {"accountId": "synthetic-duplicate"},
            ],
        }
        self.assertEqual(
            semantic_error_keywords("urn:agent-state-protocol:v1:accounts:account-source-collection", source_collection),
            {"uniqueAccountId"},
        )
        self.assertEqual(
            semantic_error_keywords("urn:agent-state-protocol:v1:accounts:account-nickname-collection", nickname_collection),
            {"uniqueAccountId"},
        )
        self.assertEqual(semantic_error_keywords("urn:agent-state-protocol:v1:accounts:account-collection", source_collection), set())


if __name__ == "__main__":
    unittest.main()
