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
    "schemas/v1/common/capability-descriptor.schema.json",
    "schemas/v1/common/error-detail.schema.json",
    "schemas/v1/common/secret-reference.schema.json",
    "schemas/v1/credentials/credential-descriptor.schema.json",
    "schemas/v1/providers/provider-descriptor.schema.json",
    "schemas/v1/usage/usage-snapshot.schema.json",
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
        example_path = root / "examples" / "v1" / f"{schema_path.name.removesuffix('.schema.json')}.example.json"
        manifest_schemas.append(
            {
                "id": schema_id,
                "path": relative_posix(root, schema_path),
                "sha256": hashlib.sha256(canonical_bytes(schema_path)).hexdigest(),
                "examples": [relative_posix(root, example_path)],
            }
        )
    return {
        "protocol": "agent-state-protocol",
        "schemaVersion": 1,
        "dialect": DIALECT,
        "schemas": manifest_schemas,
    }


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
        schemas_by_id[schema_id] = (path, schema)

    reference_count = check_references(schemas_by_id)
    registry = Registry()
    for schema_id, (_, schema) in schemas_by_id.items():
        registry = registry.with_resource(schema_id, Resource.from_contents(schema))
    format_checker = FormatChecker()
    example_paths = sorted(example_directory.glob("*.example.json"))
    expected_examples = {
        example_directory / f"{path.name.removesuffix('.schema.json')}.example.json"
        for path in schema_paths
    }
    if set(example_paths) != expected_examples:
        raise ValueError("positive example set must contain exactly one matching example per schema")

    for schema_id, (schema_path, schema) in schemas_by_id.items():
        example_path = example_directory / f"{schema_path.name.removesuffix('.schema.json')}.example.json"
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

        validator = Draft202012Validator(schema, registry=registry, format_checker=format_checker)
        errors = sorted(validator.iter_errors(example), key=lambda error: list(error.path))
        if errors:
            raise ValueError(f"positive example does not validate ({example_path}): {errors[0].message}")

    negative_directory = ROOT / "tests" / "negative-fixtures"
    negative_paths = sorted(negative_directory.glob("*.json"))
    if not negative_paths:
        raise ValueError("at least one deliberately invalid fixture is required")
    for path in negative_paths:
        fixture = load_json(path)
        if not isinstance(fixture, dict) or set(fixture) != {"schemaId", "instance"}:
            raise ValueError(f"negative fixture shape is invalid: {path}")
        fixture_schema = schemas_by_id.get(fixture["schemaId"])
        if fixture_schema is None:
            raise ValueError(f"negative fixture references unknown schema: {path}")
        validator = Draft202012Validator(fixture_schema[1], registry=registry, format_checker=format_checker)
        if validator.is_valid(fixture["instance"]):
            raise ValueError(f"negative fixture unexpectedly validates: {path}")

    manifest_path = ROOT / "protocol-manifest.json"
    manifest = expected_manifest(ROOT, schemas_by_id)
    if update_manifest:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    elif load_json(manifest_path) != manifest:
        raise ValueError("protocol-manifest.json does not match canonical schema paths and SHA-256 digests")

    manifest_text = manifest_path.read_text(encoding="utf-8")
    if EMAIL_PATTERN.search(manifest_text) or WINDOWS_PATH_PATTERN.search(manifest_text) or PRIVATE_UNIX_PATH_PATTERN.search(manifest_text):
        raise ValueError("manifest contains an email-like value or machine-specific path")

    print(f"Validated {len(schemas_by_id)} Draft 2020-12 schemas and {len(example_paths)} positive examples.")
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
