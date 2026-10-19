"""Resolve requested services against private enablement and release metadata."""

from __future__ import annotations


class ServiceSelectionError(ValueError):
    """A requested or required service cannot be selected safely."""


def resolve_services(
    release_services: dict,
    enabled_services: list[str],
    requested_service: str | None = None,
) -> list[str]:
    """Return a deterministic dependency-first service order.

    ``release_services`` is the validated release manifest's service mapping;
    its ``dependencies`` fields are the sole dependency graph.
    """
    if not isinstance(release_services, dict) or not release_services:
        raise ServiceSelectionError("release services must be a non-empty mapping")
    known = set(release_services)
    if (
        not isinstance(enabled_services, list)
        or any(not isinstance(name, str) or not name for name in enabled_services)
        or len(enabled_services) != len(set(enabled_services))
    ):
        raise ServiceSelectionError("enabled services must be a unique list of names")
    enabled = set(enabled_services)
    unknown_enabled = enabled - known
    if unknown_enabled:
        raise ServiceSelectionError(
            "enabled service(s) are absent from the release: "
            + ", ".join(sorted(unknown_enabled))
        )
    if requested_service is None:
        roots = sorted(enabled)
    else:
        if requested_service not in known:
            raise ServiceSelectionError(f"unknown service: {requested_service}")
        if requested_service not in enabled:
            raise ServiceSelectionError(f"service is disabled: {requested_service}")
        roots = [requested_service]

    ordered: list[str] = []
    active: set[str] = set()
    complete: set[str] = set()

    def visit(name: str) -> None:
        if name in active:
            raise ServiceSelectionError(f"dependency cycle includes {name}")
        if name in complete:
            return
        if name not in known:
            raise ServiceSelectionError(f"required dependency is missing: {name}")
        if name not in enabled:
            raise ServiceSelectionError(f"required dependency is disabled: {name}")
        entry = release_services[name]
        if not isinstance(entry, dict):
            raise ServiceSelectionError(f"invalid release entry for {name}")
        dependencies = entry.get("dependencies")
        if (
            not isinstance(dependencies, list)
            or any(not isinstance(item, str) or not item for item in dependencies)
            or len(dependencies) != len(set(dependencies))
        ):
            raise ServiceSelectionError(f"invalid dependencies for {name}")
        active.add(name)
        for dependency in sorted(dependencies):
            visit(dependency)
        active.remove(name)
        complete.add(name)
        ordered.append(name)

    for root in roots:
        visit(root)
    return ordered
