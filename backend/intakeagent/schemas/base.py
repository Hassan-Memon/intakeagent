"""Shared building blocks for intake schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Vertical = Literal["healthcare", "legal"]


class Evidence(BaseModel):
    """Where in the transcript a value came from.

    ``start`` and ``end`` are character offsets into the merged transcript so the review UI
    can highlight the exact span. ``segment_id`` points at the audio segment for playback.
    """

    quote: str
    start: int = -1
    end: int = -1
    segment_id: str | None = None


class Coding(BaseModel):
    """A code from a standard terminology (FHIR ``Coding``): RxNorm, ICD-10-CM, ..."""

    system: str
    code: str
    display: str


class Extracted[T](BaseModel):
    """A single extracted value plus its provenance."""

    value: T | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @property
    def present(self) -> bool:
        v = self.value
        if v is None:
            return False
        if isinstance(v, str):
            return bool(v.strip())
        if isinstance(v, list | dict):
            return len(v) > 0
        return True


def intake_field(
    *,
    required: bool,
    question: str,
    description: str = "",
    group: str = "general",
    default: Any = None,
) -> Any:
    """Declare an intake field with the metadata the graph needs.

    ``required`` drives the missing-field detector. ``question`` is what the agent asks when
    the field is empty. ``group`` is used by the review UI to lay out the form.
    """
    return Field(
        default_factory=Extracted if default is None else default,
        description=description,
        json_schema_extra={
            "required_for_intake": required,
            "question": question,
            "group": group,
        },
    )


class FieldSpec(BaseModel):
    name: str
    required: bool
    question: str
    group: str
    description: str = ""
    kind: Literal["scalar", "list"] = "scalar"


def field_specs(model: type[BaseModel]) -> list[FieldSpec]:
    """Read field metadata back out of a schema class in declaration order."""
    specs: list[FieldSpec] = []
    for name, info in model.model_fields.items():
        extra = info.json_schema_extra if isinstance(info.json_schema_extra, dict) else {}
        if "required_for_intake" not in extra:
            continue
        kind: Literal["scalar", "list"] = "scalar"
        ann = str(info.annotation)
        if "list[" in ann:
            kind = "list"
        specs.append(
            FieldSpec(
                name=name,
                required=bool(extra["required_for_intake"]),
                question=str(extra["question"]),
                group=str(extra.get("group", "general")),
                description=info.description or "",
                kind=kind,
            )
        )
    return specs


def missing_required(record: BaseModel) -> list[str]:
    """Return names of required fields whose Extracted value is empty."""
    missing: list[str] = []
    for spec in field_specs(type(record)):
        if not spec.required:
            continue
        value = getattr(record, spec.name)
        if isinstance(value, Extracted) and not value.present:
            missing.append(spec.name)
    return missing
