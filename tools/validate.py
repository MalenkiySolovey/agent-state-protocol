#!/usr/bin/env python3
"""Validate the canonical Agent State Protocol schemas and synthetic examples."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_PREFIX = "urn:agent-state-protocol:v1:"
EXPECTED_SCHEMA_PATHS = {
    "schemas/v1/accounts/account-collection.schema.json",
    "schemas/v1/accounts/account-descriptor.schema.json",
    "schemas/v1/accounts/account-metadata-update.schema.json",
    "schemas/v1/accounts/account-nickname-collection.schema.json",
    "schemas/v1/accounts/account-nickname-mutation.schema.json",
    "schemas/v1/accounts/account-nickname-state.schema.json",
    "schemas/v1/accounts/account-source-collection.schema.json",
    "schemas/v1/accounts/account-source-descriptor.schema.json",
    "schemas/v1/common/capability-descriptor.schema.json",
    "schemas/v1/common/error-detail.schema.json",
    "schemas/v1/common/secret-reference.schema.json",
    "schemas/v1/credentials/credential-descriptor.schema.json",
    "schemas/v1/providers/provider-descriptor.schema.json",
    "schemas/v1/usage/usage-snapshot.schema.json",
}
EXPECTED_EXAMPLES_BY_SCHEMA = {
    "schemas/v1/accounts/account-collection.schema.json": ("examples/v1/account-collection.example.json",),
    "schemas/v1/accounts/account-descriptor.schema.json": ("examples/v1/account-descriptor.example.json",),
    "schemas/v1/accounts/account-metadata-update.schema.json": ("examples/v1/account-metadata-update.example.json",),
    "schemas/v1/accounts/account-nickname-collection.schema.json": ("examples/v1/account-nickname-collection.example.json",),
    "schemas/v1/accounts/account-nickname-mutation.schema.json": (
        "examples/v1/account-nickname-mutation-at.example.json",
        "examples/v1/account-nickname-mutation-clear.example.json",
        "examples/v1/account-nickname-mutation-rename.example.json",
        "examples/v1/account-nickname-mutation.example.json",
    ),
    "schemas/v1/accounts/account-nickname-state.schema.json": (
        "examples/v1/account-nickname-state-at.example.json",
        "examples/v1/account-nickname-state-null.example.json",
        "examples/v1/account-nickname-state.example.json",
    ),
    "schemas/v1/accounts/account-source-collection.schema.json": ("examples/v1/account-source-collection.example.json",),
    "schemas/v1/accounts/account-source-descriptor.schema.json": ("examples/v1/account-source-descriptor.example.json",),
    "schemas/v1/common/capability-descriptor.schema.json": ("examples/v1/capability-descriptor.example.json",),
    "schemas/v1/common/error-detail.schema.json": ("examples/v1/error-detail.example.json",),
    "schemas/v1/common/secret-reference.schema.json": ("examples/v1/secret-reference.example.json",),
    "schemas/v1/credentials/credential-descriptor.schema.json": ("examples/v1/credential-descriptor.example.json",),
    "schemas/v1/providers/provider-descriptor.schema.json": ("examples/v1/provider-descriptor.example.json",),
    "schemas/v1/usage/usage-snapshot.schema.json": ("examples/v1/usage-snapshot.example.json",),
}
FORBIDDEN_PROPERTY_NAMES = {
    "accesstoken",
    "oauthaccesstoken",
    "refreshtoken",
    "oauthrefreshtoken",
    "idtoken",
    "apikey",
    "totpsecret",
    "totpseed",
    "password",
    "authjson",
    "rawauthjson",
    "dpapiblob",
    "decryptedvaultrecord",
    "plaintextsecret",
    "secretvalue",
    "credentialbytes",
}
SOURCE_METADATA_FORBIDDEN_FIELDS = {
    "nickname",
    "email",
    "accountemail",
    "basedisplayname",
    "detecteddisplayname",
}
EMAIL_PATTERN = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:\\")
PRIVATE_UNIX_PATH_PATTERN = re.compile(r"/(?:Users|home|root|Volumes)/")


def duplicate_rejecting_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON property: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=duplicate_rejecting_object)


def walk(value: object):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def canonical_bytes(path: Path) -> bytes:
    # Git stores text with LF under .gitattributes; normalize Windows worktrees before hashing.
    return path.read_bytes().replace(b"\r\n", b"\n")


def relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def property_name_is_forbidden(name: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", name.lower())
    return normalized in FORBIDDEN_PROPERTY_NAMES


def schema_property_names(schema: object):
    for node in walk(schema):
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                yield from properties.keys()


def example_property_names(instance: object):
    if isinstance(instance, dict):
        for key, child in instance.items():
            yield key
            yield from example_property_names(child)
    elif isinstance(instance, list):
        for child in instance:
            yield from example_property_names(child)


def resolve_pointer(document: object, fragment: str, label: str) -> None:
    if not fragment:
        return
    pointer = unquote(fragment)
    if not pointer.startswith("/"):
        raise ValueError(f"unsupported or unresolved $ref anchor in {label}: #{fragment}")
    current = document
    for raw_segment in pointer[1:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(current, dict):
                current = current[segment]
            elif isinstance(current, list):
                current = current[int(segment)]
            else:
                raise KeyError(segment)
        except (KeyError, IndexError, ValueError) as error:
            raise ValueError(f"unresolved JSON Pointer in $ref for {label}: #{fragment}") from error


def check_references(schemas_by_id: dict[str, tuple[Path, dict[str, object]]]) -> int:
    reference_count = 0
    for schema_id, (path, schema) in schemas_by_id.items():
        for node in walk(schema):
            if not isinstance(node, dict) or "$ref" not in node:
                continue
            reference_count += 1
            reference = node["$ref"]
            if not isinstance(reference, str):
                raise ValueError(f"non-string $ref in {path}")
            if reference.startswith("#"):
                resolve_pointer(schema, reference[1:], relative_posix(ROOT, path))
                continue
            target_id, fragment = urldefrag(reference)
            if target_id not in schemas_by_id:
                raise ValueError(f"$ref does not resolve to a local canonical schema: {reference}")
            target_path, target_schema = schemas_by_id[target_id]
            resolve_pointer(target_schema, fragment, relative_posix(ROOT, target_path))
    return reference_count


def expected_manifest(root: Path, schemas_by_id: dict[str, tuple[Path, dict[str, object]]]) -> dict[str, object]:
    manifest_schemas = []
    for schema_id, (schema_path, schema) in sorted(schemas_by_id.items(), key=lambda item: relative_posix(root, item[1][0])):
        schema_relative_path = relative_posix(root, schema_path)
        relative_example_paths = EXPECTED_EXAMPLES_BY_SCHEMA.get(schema_relative_path)
        if not relative_example_paths:
            raise ValueError(f"schema must have a canonical base example: {schema_path}")
        example_paths = [root / example_path for example_path in relative_example_paths]
        manifest_schemas.append(
            {
                "id": schema_id,
                "path": schema_relative_path,
                "sha256": hashlib.sha256(canonical_bytes(schema_path)).hexdigest(),
                "examples": [relative_posix(root, example_path) for example_path in example_paths],
            }
        )
    return {
        "protocol": "agent-state-protocol",
        "schemaVersion": 1,
        "dialect": DIALECT,
        "schemas": manifest_schemas,
    }


def semantic_error_keywords(schema_id: str, instance: object) -> set[str]:
    """Checks accountId uniqueness, which JSON Schema cannot express by object key."""
    collection_ids = {
        f"{ID_PREFIX}accounts:account-source-collection",
        f"{ID_PREFIX}accounts:account-nickname-collection",
    }
    if schema_id not in collection_ids or not isinstance(instance, dict):
        return set()
    accounts = instance.get("accounts")
    if not isinstance(accounts, list):
        return set()
    account_ids = [
        account.get("accountId")
        for account in accounts
        if isinstance(account, dict) and isinstance(account.get("accountId"), str)
    ]
    return {"uniqueAccountId"} if len(account_ids) != len(set(account_ids)) else set()


def validate(root: Path, update_manifest: bool, format_examples: bool) -> None:
    global ROOT
    ROOT = root.resolve()
    schema_directory = ROOT / "schemas" / "v1"
    example_directory = ROOT / "examples" / "v1"
    if format_examples:
        for example_path in sorted(example_directory.glob("*.example.json")):
            example = load_json(example_path)
            example_path.write_text(
                json.dumps(example, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    schema_paths = sorted(schema_directory.rglob("*.schema.json"))
    actual_paths = {relative_posix(ROOT, path) for path in schema_paths}
    if actual_paths != EXPECTED_SCHEMA_PATHS:
        raise ValueError(
            "canonical schema set differs from the v1 contract; "
            f"missing={sorted(EXPECTED_SCHEMA_PATHS - actual_paths)}, "
            f"unexpected={sorted(actual_paths - EXPECTED_SCHEMA_PATHS)}"
        )

    schemas_by_id: dict[str, tuple[Path, dict[str, object]]] = {}
    for path in schema_paths:
        schema = load_json(path)
        if not isinstance(schema, dict):
            raise ValueError(f"schema root must be an object: {path}")
        if schema.get("$schema") != DIALECT:
            raise ValueError(f"schema must declare Draft 2020-12: {path}")
        relative_path = Path(relative_posix(ROOT, path))
        group = relative_path.parts[2]
        name = path.name.removesuffix(".schema.json")
        schema_id = schema.get("$id")
        expected_id = f"{ID_PREFIX}{group}:{name}"
        if schema_id != expected_id:
            raise ValueError(f"non-canonical or product-coupled $id in {path}: {schema_id!r}")
        if schema_id in schemas_by_id:
            raise ValueError(f"duplicate schema $id: {schema_id}")
        if "codex-control-center" in schema_id.lower():
            raise ValueError(f"Control Center schema identity remains in {path}")

        Draft202012Validator.check_schema(schema)
        if schema.get("type") != "object":
            raise ValueError(f"public records must be top-level objects: {path}")
        if schema.get("additionalProperties") is not False:
            raise ValueError(f"stable public record must close additional properties: {path}")
        if "schemaVersion" not in schema.get("required", []):
            raise ValueError(f"top-level record must require schemaVersion: {path}")
        version_schema = schema.get("properties", {}).get("schemaVersion", {})
        if version_schema.get("const") != 1:
            raise ValueError(f"top-level record must declare schemaVersion const 1: {path}")

        for node in walk(schema):
            if not isinstance(node, dict):
                continue
            if node.get("type") == "object" and isinstance(node.get("properties"), dict):
                if node.get("additionalProperties") is not False:
                    raise ValueError(f"record object must set additionalProperties: false: {path}")
            if node.get("format") == "date-time" and "Z$" not in node.get("pattern", ""):
                raise ValueError(f"date-time fields must require UTC Z timestamps: {path}")
            if "extensions" in node:
                extensions = node["extensions"]
                if not isinstance(extensions, dict) or extensions.get("type") != "object":
                    raise ValueError(f"extensions must remain an object: {path}")
                extension_values = extensions.get("additionalProperties", {}).get("type", [])
                if set(extension_values) != {"string", "number", "boolean", "null"}:
                    raise ValueError(f"extensions must remain JSON-scalar-only: {path}")

        for name in schema_property_names(schema):
            if property_name_is_forbidden(name):
                raise ValueError(f"prohibited secret property {name!r} in {path}")
        if schema_id in {
            f"{ID_PREFIX}accounts:account-source-descriptor",
            f"{ID_PREFIX}accounts:account-source-collection",
        }:
            forbidden_source_fields = SOURCE_METADATA_FORBIDDEN_FIELDS.intersection(
                re.sub(r"[^a-z0-9]", "", name.lower()) for name in schema_property_names(schema)
            )
            if forbidden_source_fields:
                raise ValueError(f"source account contract contains forbidden identity/override fields in {path}")
        schemas_by_id[schema_id] = (path, schema)

    reference_count = check_references(schemas_by_id)
    registry = Registry()
    for schema_id, (_, schema) in schemas_by_id.items():
        registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    format_checker = FormatChecker()
    example_paths = sorted(example_directory.glob("*.example.json"))
    actual_schema_inventory = {relative_posix(ROOT, path) for path in schema_paths}
    if actual_schema_inventory != set(EXPECTED_EXAMPLES_BY_SCHEMA):
        raise ValueError("schema/example inventory declaration is incomplete")
    expected_examples = {
        ROOT / example_path
        for paths in EXPECTED_EXAMPLES_BY_SCHEMA.values()
        for example_path in paths
    }
    if set(example_paths) != expected_examples:
        raise ValueError("positive examples must match the declared per-schema inventory exactly")

    total_examples = 0
    for schema_id, (schema_path, schema) in schemas_by_id.items():
        schema_relative_path = relative_posix(ROOT, schema_path)
        relative_example_paths = EXPECTED_EXAMPLES_BY_SCHEMA.get(schema_relative_path)
        if not relative_example_paths:
            raise ValueError(f"schema must have a canonical base example: {schema_path}")
        schema_example_paths = [ROOT / example_path for example_path in relative_example_paths]
        validator = Draft202012Validator(schema, registry=registry, format_checker=format_checker)
        for example_path in schema_example_paths:
            total_examples += 1
            raw_example = example_path.read_text(encoding="utf-8")
            example = load_json(example_path)
            if raw_example.replace("\r\n", "\n") != json.dumps(example, ensure_ascii=False, indent=2) + "\n":
                raise ValueError(f"example is not deterministically formatted: {example_path}")
            for name in example_property_names(example):
                if property_name_is_forbidden(name):
                    raise ValueError(f"prohibited secret property {name!r} in {example_path}")
            serialized = json.dumps(example, ensure_ascii=False)
            if EMAIL_PATTERN.search(serialized):
                raise ValueError(f"email-like value found in example: {example_path}")
            if WINDOWS_PATH_PATTERN.search(serialized) or PRIVATE_UNIX_PATH_PATTERN.search(serialized):
                raise ValueError(f"machine-specific path found in example: {example_path}")

            errors = sorted(validator.iter_errors(example), key=lambda error: list(error.path))
            if errors:
                raise ValueError(f"positive example does not validate ({example_path}): {errors[0].message}")
            semantic_errors = semantic_error_keywords(schema_id, example)
            if semantic_errors:
                raise ValueError(f"positive example violates semantic rules ({example_path}): {sorted(semantic_errors)}")

    negative_directory = ROOT / "tests" / "negative-fixtures"
    negative_paths = sorted(negative_directory.glob("*.json"))
    if not negative_paths:
        raise ValueError("at least one deliberately invalid fixture is required")
    for path in negative_paths:
        fixture = load_json(path)
        if not isinstance(fixture, dict) or set(fixture) != {"schemaId", "instance", "expectedKeyword"}:
            raise ValueError(f"negative fixture shape is invalid: {path}")
        fixture_schema = schemas_by_id.get(fixture["schemaId"])
        if fixture_schema is None:
            raise ValueError(f"negative fixture references unknown schema: {path}")
        validator = Draft202012Validator(fixture_schema[1], registry=registry, format_checker=format_checker)
        actual_keywords = {error.validator for error in validator.iter_errors(fixture["instance"])}
        actual_keywords.update(semantic_error_keywords(fixture["schemaId"], fixture["instance"]))
        if not isinstance(fixture["expectedKeyword"], str) or fixture["expectedKeyword"] not in actual_keywords:
            raise ValueError(
                f"negative fixture did not fail for its intended reason ({path}): "
                f"expected {fixture['expectedKeyword']!r}, got {sorted(actual_keywords)}"
            )

    manifest_path = ROOT / "protocol-manifest.json"
    manifest = expected_manifest(ROOT, schemas_by_id)
    if update_manifest:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    elif load_json(manifest_path) != manifest:
        raise ValueError("protocol-manifest.json does not match canonical schema paths and SHA-256 digests")

    manifest_text = manifest_path.read_text(encoding="utf-8")
    if EMAIL_PATTERN.search(manifest_text) or WINDOWS_PATH_PATTERN.search(manifest_text) or PRIVATE_UNIX_PATH_PATTERN.search(manifest_text):
        raise ValueError("manifest contains an email-like value or machine-specific path")

    print(f"Validated {len(schemas_by_id)} Draft 2020-12 schemas and {total_examples} positive examples.")
    print(f"Rejected {len(negative_paths)} deliberately invalid fixtures; resolved {reference_count} local $ref entries.")
    print("Canonical IDs, schemaVersion, UTC timestamps, strict records, secret-field and privacy checks passed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--update-manifest", action="store_true", help="rewrite the deterministic schema manifest")
    parser.add_argument("--format-examples", action="store_true", help="rewrite examples as deterministic two-space JSON")
    arguments = parser.parse_args()
    try:
        validate(arguments.root, arguments.update_manifest, arguments.format_examples)
    except Exception as error:  # report validation failures as concise CI output
        print(f"Agent State Protocol validation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
