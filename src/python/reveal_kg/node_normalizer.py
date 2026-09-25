"""
Type-equivalence normalization for cross-KG node merging.

Loads type_equivalence.json and resolves whether two raw `nodes.type` values
from different source KGs should be treated as compatible when merging.
"""

import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)


class NodeNormalizer:
    """Resolve raw node `type` strings to a canonical equivalence-group key."""

    def __init__(self, type_equivalence_path: str):
        path = Path(type_equivalence_path)
        if not path.exists():
            raise FileNotFoundError(f"Type equivalence file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f) or {}

        self._raw_type_to_group: Dict[str, str] = {}
        for group_name, entries in (config.get("groups") or {}).items():
            for entry in entries:
                raw_type = entry["type"]
                if raw_type in self._raw_type_to_group:
                    logger.warning(
                        f"Type '{raw_type}' listed in multiple groups "
                        f"('{self._raw_type_to_group[raw_type]}' and '{group_name}'); "
                        f"using '{group_name}'"
                    )
                self._raw_type_to_group[raw_type] = group_name

        logger.info(
            f"Loaded {len(self._raw_type_to_group)} type mappings across "
            f"{len(config.get('groups') or {})} equivalence groups from {path}"
        )

    def type_group(self, raw_type: str) -> str:
        """
        Return the canonical equivalence-group key for a raw `type` value.

        Types listed in type_equivalence.json resolve to their configured
        group name. Any other type falls back to its own case-insensitive
        singleton group, so it only matches an identically-spelled type.
        """
        if raw_type in self._raw_type_to_group:
            return self._raw_type_to_group[raw_type]
        return f"__type__:{raw_type.strip().lower()}"

    def is_compatible(self, type_a: str, type_b: str) -> bool:
        """True if two raw node types are allowed to merge."""
        return self.type_group(type_a) == self.type_group(type_b)
