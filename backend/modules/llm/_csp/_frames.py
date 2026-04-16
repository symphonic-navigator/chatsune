"""CSP/1 frame models. Authoritative wire format.

Matches docs/superpowers/specs/2026-04-16-chatsune-sidecar-spec.md.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class EngineInfo(BaseModel):
    type: Literal["ollama", "lmstudio", "vllm", "llamacpp"]
    version: str | None = None
    endpoint_hint: str | None = None


class HandshakeFrame(BaseModel):
    type: Literal["handshake"] = "handshake"
    csp_version: str
    sidecar_version: str
    engine: EngineInfo
    max_concurrent_requests: int = Field(ge=1)
    capabilities: list[str] = Field(default_factory=list)


class HandshakeAckFrame(BaseModel):
    type: Literal["handshake_ack"] = "handshake_ack"
    csp_version: str
    homelab_id: str | None = None
    display_name: str | None = None
    accepted: bool
    notices: list[str] = Field(default_factory=list)


class PingFrame(BaseModel):
    type: Literal["ping"] = "ping"


class PongFrame(BaseModel):
    type: Literal["pong"] = "pong"


class AuthRevokedFrame(BaseModel):
    type: Literal["auth_revoked"] = "auth_revoked"


class SupersededFrame(BaseModel):
    type: Literal["superseded"] = "superseded"


class ReqFrame(BaseModel):
    type: Literal["req"] = "req"
    id: str
    op: Literal["list_models", "generate_chat"]
    body: dict[str, Any] | None = None


class ResFrame(BaseModel):
    type: Literal["res"] = "res"
    id: str
    ok: bool
    body: dict[str, Any] | None = None


class StreamDelta(BaseModel):
    content: str | None = None
    reasoning: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


class StreamFrame(BaseModel):
    type: Literal["stream"] = "stream"
    id: str
    delta: StreamDelta


class StreamEndFrame(BaseModel):
    type: Literal["stream_end"] = "stream_end"
    id: str
    finish_reason: Literal["stop", "length", "tool_calls", "cancelled", "error"]
    usage: dict[str, int] | None = None


class ErrFrame(BaseModel):
    type: Literal["err"] = "err"
    id: str | None = None
    code: Literal[
        "model_not_found",
        "model_oom",
        "engine_unavailable",
        "engine_error",
        "invalid_request",
        "rate_limited",
        "cancelled",
        "internal",
    ]
    message: str
    detail: str | None = None
    recoverable: bool = False


class CancelFrame(BaseModel):
    type: Literal["cancel"] = "cancel"
    id: str


class ModelMeta(BaseModel):
    """Body element for list_models response."""

    slug: str
    display_name: str
    parameter_count: int | None = None
    context_length: int = Field(..., description="required; models without this are dropped before the list leaves the sidecar")
    quantisation: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    engine_family: str | None = None
    engine_model_id: str | None = None
    engine_metadata: dict[str, Any] = Field(default_factory=dict)


_FRAME_BY_TYPE: dict[str, type[BaseModel]] = {
    "handshake": HandshakeFrame,
    "handshake_ack": HandshakeAckFrame,
    "ping": PingFrame,
    "pong": PongFrame,
    "auth_revoked": AuthRevokedFrame,
    "superseded": SupersededFrame,
    "req": ReqFrame,
    "res": ResFrame,
    "stream": StreamFrame,
    "stream_end": StreamEndFrame,
    "err": ErrFrame,
    "cancel": CancelFrame,
}


def parse_frame(raw: str | bytes) -> BaseModel:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    obj = json.loads(raw)
    ftype = obj.get("type")
    cls = _FRAME_BY_TYPE.get(ftype)
    if cls is None:
        raise ValueError(f"Unknown frame type: {ftype!r}")
    return cls.model_validate(obj)


def negotiate_version(
    sidecar_version: str, backend_version: str
) -> tuple[bool, str, list[str]]:
    """Return ``(accepted, negotiated_version, notices)``.

    Major mismatch → ``accepted=False``, notices contain ``version_unsupported``.
    Minor mismatch → ``accepted=True``, version becomes ``min(a.minor, b.minor)``.
    Malformed sidecar version → rejected.
    """

    def _parse(v: str) -> tuple[int, int] | None:
        try:
            major_s, minor_s = v.split(".", 1)
            return int(major_s), int(minor_s)
        except (ValueError, AttributeError):
            return None

    sv = _parse(sidecar_version)
    bv = _parse(backend_version)
    if sv is None or bv is None:
        return False, backend_version, ["version_unsupported: malformed"]
    if sv[0] != bv[0]:
        return False, backend_version, [
            f"version_unsupported: backend requires CSP/{bv[0]}.x"
        ]
    negotiated = f"{bv[0]}.{min(sv[1], bv[1])}"
    return True, negotiated, []
