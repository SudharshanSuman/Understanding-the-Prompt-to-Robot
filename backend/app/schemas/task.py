"""Strict task schema: what a parser (LLM or deterministic) may hand to the robot side.

Every model forbids unknown fields so a provider cannot smuggle extra keys through.
Names follow the example schema in the project spec; align with
docs/INTERFACE_CONTRACTS.md once it lands.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

# Object and destination identifiers are snake_case world IDs, e.g. "red_box", "shelf_a".
Identifier = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)


class TaskAction(str, Enum):
    PICK_AND_PLACE = "pick_and_place"


class TaskConstraints(_Strict):
    avoid_objects: list[Identifier] = Field(default_factory=list)
    keep_upright: bool = False

    @field_validator("avoid_objects")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("avoid_objects must not contain duplicates")
        return value


class TaskPlan(_Strict):
    """A fully specified, unambiguous command."""

    kind: Literal["task"] = "task"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    action: TaskAction
    object: Identifier
    destination: Identifier
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _consistent(self) -> "TaskPlan":
        if self.object in self.constraints.avoid_objects:
            raise ValueError("the target object cannot also be in avoid_objects")
        if self.object == self.destination:
            raise ValueError("object and destination must differ")
        return self


class ClarificationRequest(_Strict):
    """The command cannot be executed safely until the user answers a question."""

    kind: Literal["clarification"] = "clarification"
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    question: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(default_factory=list, max_length=20)


# What a provider returns after parsing: either a plan or a clarification request.
ParsedCommand = Annotated[Union[TaskPlan, ClarificationRequest], Field(discriminator="kind")]


class RoboticTask(_Strict):
    """Spec section 6 task schema (contract CA-3), exported as RoboticTask and Task."""

    task_id: str = Field(min_length=1)
    task_type: Literal["pick_and_place"] = "pick_and_place"
    target_object: Identifier
    destination: Optional[Identifier] = None
    constraints: TaskConstraints = Field(default_factory=TaskConstraints)
    verification_required: bool = True

    @property
    def object(self) -> str:
        return self.target_object

    @classmethod
    def from_plan(cls, plan: TaskPlan, task_id: str) -> "RoboticTask":
        return cls(task_id=task_id, task_type=plan.action.value, target_object=plan.object,
                   destination=plan.destination, constraints=plan.constraints)


Task = RoboticTask


class ValidationIssue(_Strict):
    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    field: str | None = None
    message: str = Field(min_length=1)


class ValidationReport(_Strict):
    """Outcome of the deterministic safety/feasibility check."""

    ok: bool
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def _ok_matches_errors(self) -> "ValidationReport":
        if self.ok == bool(self.errors):
            raise ValueError("ok must be True exactly when there are no errors")
        return self
