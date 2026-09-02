"""Serializer canônico (PRD §57): YAML determinístico, 1 atom por arquivo.

Determinismo = mesma entrada → mesmos bytes: ordem de campos fixa (a do
envelope §14), sem sort automático, listas em ordem estável. Diffs no git
ficam legíveis e o export nunca gera commit espúrio.
"""

from pathlib import Path

import yaml

# Ordem canônica dos campos (envelope §14 + evidence/relations)
_FIELD_ORDER = [
    "id",
    "kind",
    "title",
    "description",
    "domain",
    "capability",
    "status",
    "classification",
    "confidence",
    "risk",
    "scope",
    "effective",
    "body",
    "evidence",
    "relations",
    "version",
    "created_by",
    "created_at",
    "updated_at",
]


class _Dumper(yaml.SafeDumper):
    pass


# dicts preservam ordem de inserção; nunca sort_keys
_Dumper.add_representer(
    dict,
    lambda dumper, data: dumper.represent_mapping("tag:yaml.org,2002:map", data.items()),
)


def atom_to_dict(atom, evidence: list[dict], relations: list[dict]) -> dict:
    raw = {
        "id": atom.id,
        "kind": atom.kind,
        "title": atom.title,
        "description": atom.description,
        "domain": atom.domain,
        "capability": atom.capability,
        "status": atom.status,
        "classification": atom.classification,
        "confidence": atom.confidence,
        "risk": atom.risk,
        "scope": atom.scope,
        "effective": atom.effective,
        "body": atom.body or {},
        "evidence": sorted(evidence, key=lambda e: e["id"]),
        "relations": sorted(relations, key=lambda r: (r["type"], r["to"])),
        "version": atom.version,
        "created_by": atom.created_by,
        "created_at": atom.created_at.isoformat(),
        "updated_at": atom.updated_at.isoformat(),
    }
    # body sempre presente (mesmo vazio); demais campos omitidos quando None/vazios
    return {
        k: raw[k] for k in _FIELD_ORDER if k == "body" or raw[k] not in (None, [], {})
    }


def to_yaml(data: dict) -> str:
    return yaml.dump(
        data,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=100,
    )


def atom_path(repo: Path, atom) -> Path:
    """`domain/capability/kind/ID.yaml` (§57); capability ausente vira `_global`."""
    return repo / atom.domain / (atom.capability or "_global") / atom.kind / f"{atom.id}.yaml"
