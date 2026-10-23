"""Declared model capabilities, independent of provider or parameter count.

Token estimates are conservative planning inputs, not a tokenizer or a VRAM
fit guarantee. Hosts must declare their actual context and tool overhead.
"""
from __future__ import annotations

DEFAULTS = {"reserved_output": 1024, "host_overhead": 256, "tool_tokens": 0,
            "response_mode": "native-schema", "max_response_bytes": 1_048_576}


def capabilities(config):
    supplied = config.get("capabilities", {})
    if not isinstance(supplied, dict) or set(supplied) - {*DEFAULTS, "context_window"}:
        raise ValueError("Unknown or invalid capability profile fields")
    profile = {**DEFAULTS, **supplied}
    capacity = supplied.get("context_window", config.get("context_budget"))
    if capacity is not None:
        profile["context_window"] = capacity
    for key in ("context_window", "reserved_output", "host_overhead", "tool_tokens", "max_response_bytes"):
        value = profile.get(key)
        if value is None and key == "context_window":
            continue
        minimum = 1 if key in {"context_window", "max_response_bytes"} else 0
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= 100_000_000:
            raise ValueError("Capability " + key + " must be a bounded integer")
    if profile["response_mode"] not in {"native-schema", "json"}:
        raise ValueError("response_mode must be native-schema or json; review validation is mandatory in both")
    return profile


def role_config(runtime, role):
    result = {k: v for k, v in runtime.items() if k != "roles"}
    override = runtime.get("roles", {}).get(role, {})
    result.update(override)
    if "capabilities" in runtime or "capabilities" in override:
        result["capabilities"] = {**runtime.get("capabilities", {}), **override.get("capabilities", {})}
    return result


def preflight(profile, prompt_tokens, mandated_tokens, schema_tokens, capacity=None):
    if capacity is None:
        capacity = profile.get("context_window")
    if capacity is not None and (isinstance(capacity, bool) or not isinstance(capacity, int) or capacity <= 0):
        raise ValueError("Context capacity must be a positive integer")
    parts = {"prompt": prompt_tokens, "mandated_reads": mandated_tokens, "schema": schema_tokens,
             **{k: profile[k] for k in ("reserved_output", "host_overhead", "tool_tokens")}}
    total = sum(parts.values())
    return {**parts, "total": total, "capacity": capacity,
            "fits": capacity is None or total <= capacity,
            "assurance": "character-estimate-v1", "capacity_declared": capacity is not None}
