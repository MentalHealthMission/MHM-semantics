"""Versioned contract for executable semantic operations.

The contract describes what a semantic operation means and requires without
binding it to a study, pipeline runner, or user interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import yaml

from .rules_catalog import extract_rule_dependencies, extract_rule_tokens


SCHEMA_VERSION = 1
REQUIREMENT_OPERATORS = frozenset({"concept", "allOf", "anyOf"})
PARAMETER_TYPES = frozenset({"integer", "number", "string", "boolean"})


class ExecutionProfileError(ValueError):
    """Raised when a semantic execution profile is malformed or inconsistent."""


@dataclass(frozen=True)
class RequirementExpression:
    operator: str
    concept: str = ""
    role: str = "evidence"
    children: tuple["RequirementExpression", ...] = ()

    @property
    def concepts(self) -> frozenset[str]:
        if self.operator == "concept":
            return frozenset({self.concept})
        return frozenset(value for child in self.children for value in child.concepts)

    def to_dict(self) -> dict[str, Any]:
        if self.operator == "concept":
            payload: dict[str, Any] = {"concept": self.concept}
            if self.role != "evidence":
                payload["role"] = self.role
            return payload
        return {self.operator: [child.to_dict() for child in self.children]}


@dataclass(frozen=True)
class ParameterDefinition:
    name: str
    value_type: str
    required: bool
    has_default: bool
    default: Any = None
    unit: str = ""
    minimum: int | float | None = None
    maximum: int | float | None = None
    fixed: bool = False

    def validate_value(self, value: Any) -> None:
        if self.value_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ExecutionProfileError(f"Parameter {self.name} requires an integer")
        if self.value_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            raise ExecutionProfileError(f"Parameter {self.name} requires a number")
        if self.value_type == "string" and not isinstance(value, str):
            raise ExecutionProfileError(f"Parameter {self.name} requires a string")
        if self.value_type == "boolean" and not isinstance(value, bool):
            raise ExecutionProfileError(f"Parameter {self.name} requires a boolean")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if self.minimum is not None and value < self.minimum:
                raise ExecutionProfileError(f"Parameter {self.name} is below its minimum")
            if self.maximum is not None and value > self.maximum:
                raise ExecutionProfileError(f"Parameter {self.name} is above its maximum")


@dataclass(frozen=True)
class RuleReference:
    rule_id: str
    path: str


@dataclass(frozen=True)
class OutputDefinition:
    concept: str
    kind: str
    granularity: str
    artifacts: tuple[str, ...]


@dataclass(frozen=True)
class SemanticOperation:
    operation_id: str
    label: str
    description: str
    output: OutputDefinition
    rule: RuleReference
    requirements: RequirementExpression
    parameters: tuple[ParameterDefinition, ...]
    evidence_policy: str

    @property
    def parameter_by_name(self) -> Mapping[str, ParameterDefinition]:
        return {parameter.name: parameter for parameter in self.parameters}

    def bind_parameters(self, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
        supplied = dict(values or {})
        unknown = sorted(set(supplied).difference(self.parameter_by_name))
        if unknown:
            raise ExecutionProfileError(
                f"Unknown parameters for {self.operation_id}: {', '.join(unknown)}"
            )
        bound: dict[str, Any] = {}
        for parameter in self.parameters:
            if parameter.name in supplied:
                if parameter.fixed and parameter.has_default and supplied[parameter.name] != parameter.default:
                    raise ExecutionProfileError(f"Parameter {parameter.name} is fixed")
                value = supplied[parameter.name]
            elif parameter.has_default:
                value = parameter.default
            elif parameter.required:
                raise ExecutionProfileError(f"Parameter {parameter.name} is required")
            else:
                continue
            parameter.validate_value(value)
            bound[parameter.name] = value
        return bound


@dataclass(frozen=True)
class SemanticExecutionProfile:
    schema_version: int
    profile_id: str
    namespaces: Mapping[str, str]
    operations: tuple[SemanticOperation, ...]

    @property
    def operation_by_id(self) -> Mapping[str, SemanticOperation]:
        return {operation.operation_id: operation for operation in self.operations}

    @property
    def operation_by_output(self) -> Mapping[str, SemanticOperation]:
        return {operation.output.concept: operation for operation in self.operations}


def load_execution_profile(path: Path) -> SemanticExecutionProfile:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ExecutionProfileError("Semantic execution profile must be a mapping")
    return parse_execution_profile(payload)


def parse_execution_profile(payload: Mapping[str, Any]) -> SemanticExecutionProfile:
    version = payload.get("schemaVersion")
    if version != SCHEMA_VERSION:
        raise ExecutionProfileError(
            f"Unsupported semantic execution profile schemaVersion: {version!r}"
        )
    profile_id = _required_text(payload, "profileId", "profile")
    namespaces = _parse_namespaces(payload.get("namespaces") or {})
    raw_operations = payload.get("operations") or []
    if not isinstance(raw_operations, list):
        raise ExecutionProfileError("operations must be a list")
    operations = tuple(_parse_operation(raw, namespaces) for raw in raw_operations)
    _assert_unique((operation.operation_id for operation in operations), "operation id")
    _assert_unique((operation.output.concept for operation in operations), "output concept")
    return SemanticExecutionProfile(
        schema_version=version,
        profile_id=profile_id,
        namespaces=namespaces,
        operations=operations,
    )


def validate_profile_rules(profile: SemanticExecutionProfile, *, repo_root: Path) -> None:
    """Check that every declared rule agrees with its authored SPARQL source."""

    for operation in profile.operations:
        rule_path = _resolve_relative_path(repo_root, operation.rule.path)
        if not rule_path.exists():
            raise ExecutionProfileError(f"Rule does not exist for {operation.operation_id}: {operation.rule.path}")
        output, dependencies, _, _ = extract_rule_dependencies(rule_path, repo_root)
        if output != operation.output.concept:
            raise ExecutionProfileError(
                f"Rule output for {operation.operation_id} is {output}, not {operation.output.concept}"
            )
        declared_dependencies = operation.requirements.concepts
        if set(dependencies) != set(declared_dependencies):
            missing = sorted(set(dependencies).difference(declared_dependencies))
            extra = sorted(set(declared_dependencies).difference(dependencies))
            raise ExecutionProfileError(
                f"Rule requirements differ for {operation.operation_id}; missing={missing}, extra={extra}"
            )
        extracted_parameters = {item["name"] for item in extract_rule_tokens(rule_path)}
        declared_parameters = set(operation.parameter_by_name)
        if extracted_parameters != declared_parameters:
            missing = sorted(extracted_parameters.difference(declared_parameters))
            extra = sorted(declared_parameters.difference(extracted_parameters))
            raise ExecutionProfileError(
                f"Rule parameters differ for {operation.operation_id}; missing={missing}, extra={extra}"
            )


def legacy_phenotype_catalog(profile: SemanticExecutionProfile) -> dict[str, Any]:
    """Project the v1 contract for callers that still consume the flat catalogue."""

    phenotypes: dict[str, Any] = {}
    for operation in sorted(profile.operations, key=lambda item: item.output.concept):
        tokens = []
        for parameter in operation.parameters:
            token: dict[str, Any] = {
                "name": parameter.name,
                "type": parameter.value_type,
                "has_default": parameter.has_default,
            }
            if parameter.has_default:
                token["default"] = parameter.default
            if parameter.unit:
                token["unit"] = parameter.unit
            tokens.append(token)
        phenotypes[operation.output.concept] = {
            "rule": operation.rule.path,
            "depends_on": sorted(operation.requirements.concepts),
            "requirements": operation.requirements.to_dict(),
            "doc": operation.description,
            "tokens": tokens,
            "operation_id": operation.operation_id,
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedFrom": profile.profile_id,
        "phenotypes": phenotypes,
    }


def _parse_operation(raw: Any, namespaces: Mapping[str, str]) -> SemanticOperation:
    if not isinstance(raw, Mapping):
        raise ExecutionProfileError("Each operation must be a mapping")
    operation_id = _required_text(raw, "id", "operation")
    output_raw = raw.get("output") or {}
    if not isinstance(output_raw, Mapping):
        raise ExecutionProfileError(f"output must be a mapping for {operation_id}")
    output = OutputDefinition(
        concept=_curie(output_raw.get("concept"), namespaces, f"output concept for {operation_id}"),
        kind=_required_text(output_raw, "kind", f"output for {operation_id}"),
        granularity=str(output_raw.get("granularity") or "day").strip(),
        artifacts=tuple(_strings(output_raw.get("artifacts") or ["semantic-results.csv", "ontology.ttl"])),
    )
    rule_raw = raw.get("rule") or {}
    if not isinstance(rule_raw, Mapping):
        raise ExecutionProfileError(f"rule must be a mapping for {operation_id}")
    rule = RuleReference(
        rule_id=_required_text(rule_raw, "id", f"rule for {operation_id}"),
        path=_relative_locator(_required_text(rule_raw, "path", f"rule for {operation_id}")),
    )
    requirements = _parse_requirement(raw.get("requirements") or {"allOf": []}, namespaces)
    parameters_raw = raw.get("parameters") or []
    if not isinstance(parameters_raw, list):
        raise ExecutionProfileError(f"parameters must be a list for {operation_id}")
    parameters = tuple(_parse_parameter(item, operation_id) for item in parameters_raw)
    _assert_unique((parameter.name for parameter in parameters), f"parameter in {operation_id}")
    return SemanticOperation(
        operation_id=operation_id,
        label=str(raw.get("label") or output.concept).strip(),
        description=str(raw.get("description") or "").strip(),
        output=output,
        rule=rule,
        requirements=requirements,
        parameters=parameters,
        evidence_policy=str(raw.get("evidencePolicy") or "all-feasible-routes").strip(),
    )


def _parse_requirement(raw: Any, namespaces: Mapping[str, str]) -> RequirementExpression:
    if not isinstance(raw, Mapping):
        raise ExecutionProfileError("Requirement expression must be a mapping")
    present = [key for key in REQUIREMENT_OPERATORS if key in raw]
    if len(present) != 1:
        raise ExecutionProfileError("Requirement expression must contain exactly one of concept, allOf, anyOf")
    operator = present[0]
    if operator == "concept":
        return RequirementExpression(
            operator="concept",
            concept=_curie(raw.get("concept"), namespaces, "requirement concept"),
            role=str(raw.get("role") or "evidence").strip(),
        )
    children_raw = raw.get(operator)
    if not isinstance(children_raw, list):
        raise ExecutionProfileError(f"{operator} must be a list")
    children = tuple(_parse_requirement(child, namespaces) for child in children_raw)
    if operator == "anyOf" and not children:
        raise ExecutionProfileError("anyOf must contain at least one requirement")
    return RequirementExpression(operator=operator, children=children)


def _parse_parameter(raw: Any, operation_id: str) -> ParameterDefinition:
    if not isinstance(raw, Mapping):
        raise ExecutionProfileError(f"Parameter in {operation_id} must be a mapping")
    name = _required_text(raw, "name", f"parameter in {operation_id}")
    value_type = str(raw.get("type") or "number").strip()
    if value_type not in PARAMETER_TYPES:
        raise ExecutionProfileError(f"Unsupported parameter type for {name}: {value_type}")
    has_default = "default" in raw
    parameter = ParameterDefinition(
        name=name,
        value_type=value_type,
        required=bool(raw.get("required", not has_default)),
        has_default=has_default,
        default=raw.get("default"),
        unit=str(raw.get("unit") or "").strip(),
        minimum=raw.get("minimum"),
        maximum=raw.get("maximum"),
        fixed=bool(raw.get("fixed", False)),
    )
    if has_default:
        parameter.validate_value(parameter.default)
    return parameter


def _parse_namespaces(raw: Any) -> Mapping[str, str]:
    if not isinstance(raw, Mapping):
        raise ExecutionProfileError("namespaces must be a mapping")
    namespaces = {str(key).strip(): str(value).strip() for key, value in raw.items()}
    for prefix, value in namespaces.items():
        if not prefix or not value:
            raise ExecutionProfileError("Namespace prefixes and values must be non-empty")
    return namespaces


def _curie(raw: Any, namespaces: Mapping[str, str], label: str) -> str:
    value = str(raw or "").strip()
    if not value or ":" not in value:
        raise ExecutionProfileError(f"{label} must be a CURIE")
    prefix = value.split(":", 1)[0]
    if prefix not in namespaces:
        raise ExecutionProfileError(f"Unknown namespace prefix in {label}: {prefix}")
    return value


def _relative_locator(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise ExecutionProfileError(f"Rule path must be repository-relative: {value}")
    return path.as_posix()


def _resolve_relative_path(root: Path, locator: str) -> Path:
    return root / PurePosixPath(locator)


def _required_text(raw: Mapping[str, Any], key: str, label: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise ExecutionProfileError(f"{key} is required for {label}")
    return value


def _strings(raw: Iterable[Any]) -> list[str]:
    values = [str(value).strip() for value in raw if str(value).strip()]
    if not values:
        raise ExecutionProfileError("At least one output artifact must be declared")
    return values


def _assert_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    if duplicates:
        raise ExecutionProfileError(f"Duplicate {label}: {', '.join(sorted(duplicates))}")


__all__ = [
    "ExecutionProfileError",
    "OutputDefinition",
    "ParameterDefinition",
    "RequirementExpression",
    "RuleReference",
    "SCHEMA_VERSION",
    "SemanticExecutionProfile",
    "SemanticOperation",
    "load_execution_profile",
    "legacy_phenotype_catalog",
    "parse_execution_profile",
    "validate_profile_rules",
]
