"""
Cross-KG node merging engine.

Simple, two-pass design - no ATTACH/DETACH, no cross-database SQL. Each
source database is opened read-only with its own plain connection; matching
state (which identifier values already exist, and under which canonical
node) is kept in memory in Python for the whole run.

Pass 1 (nodes): process every source, in priority order. A source node
merges into an existing canonical node if it shares an identical
`identifiers.identifier_value` with a compatible `type` (see NodeNormalizer);
otherwise it becomes a new canonical node. All node/identifier/property work
for every source completes before pass 2 starts.

Pass 2 (edges): process every source again, translating each edge's
source/target node id through the pass-1 mapping (nodes that weren't merged
keep their original id) and copying it - and its edge_properties - into the
output database.

Nodes are never merged with other nodes from the SAME source - each
source's own loader is assumed to already be internally deduplicated.

Merge order = priority order: the first source's node wins any label/type
conflict; the losing source's label/type is stored as an `alt_label`/
`alt_type` node property instead of overwriting the canonical value.

Edges are copied from every source unchanged (never deduplicated across
sources). `properties` rows are deduplicated by (property_key,
property_value, value_type) via an in-memory index, so identical property
values across sources share one row.

If debug_db_path is set, the node-merge mapping and any mismatch/ambiguous-
match records are written to that separate SQLite file, so the merged
output database only ever contains the standard kg_schema.sql tables.
"""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from kg_database import DatabaseManager
from node_normalizer import NodeNormalizer

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50_000
_PROGRESS_EVERY = 500_000


def _open_source(path: str) -> sqlite3.Connection:
    """Open a source database read-only (own connection - never ATTACHed), so
    the merge never writes to it and never contends for locks on it."""
    uri = f"file:{Path(path).resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@dataclass
class SourceSpec:
    name: str
    path: str


class MergeStats:
    """Per-source counters (and detail rows, for the debug db) for the merge summary report."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.nodes_read = 0
        self.nodes_merged = 0
        self.nodes_added = 0
        self.ambiguous_matches = 0
        self.label_or_type_mismatches = 0
        self.edges_copied = 0
        # Detail rows for the debug db (empty if no debug_db_path was configured).
        self.mismatch_rows: List[tuple] = []
        self.ambiguous_rows: List[tuple] = []

    def as_dict(self) -> dict:
        return {
            "source": self.source_name,
            "nodes_read": self.nodes_read,
            "nodes_merged": self.nodes_merged,
            "nodes_added": self.nodes_added,
            "ambiguous_matches": self.ambiguous_matches,
            "label_or_type_mismatches": self.label_or_type_mismatches,
            "edges_copied": self.edges_copied,
        }


class KGMerger:
    """Merge multiple source KG databases into one output database, in priority order."""

    def __init__(
        self,
        db: DatabaseManager,
        normalizer: NodeNormalizer,
        sources: List[SourceSpec],
        debug_db_path: Optional[str] = None,
        identifier_prefix_mapping: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
    ):
        self.db = db
        self.normalizer = normalizer
        self.sources = sources
        self.debug_db_path = debug_db_path
        # identifier_type -> {prefix -> {mapped_type, mapped_prefix}}, see merge_config.json
        self._identifier_prefix_mapping = identifier_prefix_mapping or {}
        self.stats: Dict[str, MergeStats] = {s.name: MergeStats(s.name) for s in sources}

        # identifier_value -> canonical_node_id
        self._identifier_index: Dict[str, str] = {}
        # canonical_node_id -> (type, label), for the node that currently owns it
        self._canonical_meta: Dict[str, Tuple[str, str]] = {}
        # source_name -> {src_node_id: canonical_node_id}, merged nodes only
        # (nodes that became new canonical nodes keep their own id, no entry needed)
        self._node_id_map: Dict[str, Dict[str, str]] = {s.name: {} for s in sources}
        # (property_key, property_value, value_type) -> output property_id
        self._property_index: Dict[Tuple[str, str, str], int] = {}
        self._next_property_id = 1
        self._next_edge_id = 1

    def run(self):
        assert self.db.conn is not None and self.db.cursor is not None

        logger.info("=== Phase 1: merging nodes (all sources) ===")
        for source in self.sources:
            logger.info(f"Merging nodes from '{source.name}' ({source.path})")
            self._merge_nodes_for_source(source)
            stats = self.stats[source.name]
            logger.info(
                f"Source '{source.name}' nodes: read={stats.nodes_read} "
                f"merged_into_existing={stats.nodes_merged} added_as_new={stats.nodes_added}"
            )

        logger.info("=== Phase 2: copying edges (all sources) ===")
        for source in self.sources:
            logger.info(f"Copying edges from '{source.name}' ({source.path})")
            self._copy_edges_for_source(source)
            logger.info(f"Source '{source.name}' edges: copied={self.stats[source.name].edges_copied}")

        if self.debug_db_path:
            logger.info(f"Writing debug mapping data to {self.debug_db_path}")
            self._write_debug_db()

        self._log_summary()

    # ------------------------------------------------------------------
    # Pass 1: nodes
    # ------------------------------------------------------------------

    def _merge_nodes_for_source(self, source: SourceSpec):
        stats = self.stats[source.name]
        src_conn = _open_source(source.path)
        try:
            node_identifiers = self._read_identifiers_by_node(src_conn)

            node_batch: List[Tuple[str, str, str]] = []
            identifier_batch: List[Tuple[str, str, str]] = []
            node_property_rows: List[Tuple[str, str, str, str]] = []

            for src_node_id, src_type, src_label in src_conn.execute("SELECT node_id, type, label FROM nodes"):
                stats.nodes_read += 1
                ids_for_node = node_identifiers.get(src_node_id, [])

                canonical_id = self._find_canonical_match(src_type, ids_for_node, source.name, src_node_id, stats)

                if canonical_id is None:
                    canonical_id = src_node_id
                    node_batch.append((canonical_id, src_type, src_label))
                    self._canonical_meta[canonical_id] = (src_type, src_label)
                    for id_type, id_value in ids_for_node:
                        identifier_batch.append((canonical_id, id_type, id_value))
                        self._identifier_index.setdefault(id_value, canonical_id)
                    stats.nodes_added += 1
                else:
                    self._node_id_map[source.name][src_node_id] = canonical_id
                    for id_type, id_value in ids_for_node:
                        identifier_batch.append((canonical_id, id_type, id_value))
                        self._identifier_index.setdefault(id_value, canonical_id)
                    stats.nodes_merged += 1
                    self._record_label_type_mismatch(
                        source.name, src_node_id, canonical_id, src_type, src_label, node_property_rows, stats
                    )

                if len(node_batch) >= _BATCH_SIZE:
                    self._flush_nodes(node_batch, identifier_batch, node_property_rows)
                    node_batch, identifier_batch, node_property_rows = [], [], []

                if stats.nodes_read % _PROGRESS_EVERY == 0:
                    logger.info(f"  ... {stats.nodes_read} nodes processed from '{source.name}'")

            self._flush_nodes(node_batch, identifier_batch, node_property_rows)
            self._commit()

            self._copy_node_properties_for_source(src_conn, source)
            self._commit()
        finally:
            src_conn.close()

    def _commit(self):
        assert self.db.conn is not None
        self.db.conn.commit()

    def _read_identifiers_by_node(self, src_conn: sqlite3.Connection) -> Dict[str, List[Tuple[str, str]]]:
        result: Dict[str, List[Tuple[str, str]]] = {}
        for node_id, id_type, id_value in src_conn.execute(
            "SELECT node_id, identifier_type, identifier_value FROM identifiers"
        ):
            id_type, id_value = self._remap_identifier(id_type, id_value)
            result.setdefault(node_id, []).append((id_type, id_value))
        return result

    def _remap_identifier(self, id_type: str, id_value: str) -> Tuple[str, str]:
        """Apply merge_config.json's identifier_prefix_mapping, e.g. ENTREZ: -> NCBIGene:."""
        prefixes = self._identifier_prefix_mapping.get(id_type)
        if not prefixes:
            return id_type, id_value
        for prefix, mapping in prefixes.items():
            if id_value.startswith(prefix):
                mapped_prefix = mapping.get("mapped_prefix", prefix)
                mapped_type = mapping.get("mapped_type", id_type)
                return mapped_type, mapped_prefix + id_value[len(prefix):]
        return id_type, id_value

    def _find_canonical_match(
        self,
        src_type: str,
        ids_for_node: List[Tuple[str, str]],
        source_name: str,
        src_node_id: str,
        stats: MergeStats,
    ) -> Optional[str]:
        """Find the existing canonical node this src node should merge into, if any."""
        candidates: Set[str] = set()
        for _, id_value in ids_for_node:
            cid = self._identifier_index.get(id_value)
            if cid is None:
                continue
            canonical_type, _ = self._canonical_meta[cid]
            if self.normalizer.is_compatible(src_type, canonical_type):
                candidates.add(cid)

        if not candidates:
            return None

        canonical_id = min(candidates)
        if len(candidates) > 1:
            stats.ambiguous_matches += 1
            stats.ambiguous_rows.append((src_node_id, len(candidates), canonical_id))
            logger.warning(
                f"Node {src_node_id} ({source_name}) matched {len(candidates)} distinct "
                "canonical nodes; merging into the smallest canonical node_id"
            )
        return canonical_id

    def _record_label_type_mismatch(
        self,
        source_name: str,
        src_node_id: str,
        canonical_id: str,
        src_type: str,
        src_label: str,
        node_property_rows: List[Tuple[str, str, str, str]],
        stats: MergeStats,
    ):
        """Log (warning-only) and preserve conflicting label/type as alt_label/alt_type properties."""
        canonical_type, canonical_label = self._canonical_meta[canonical_id]
        if src_type == canonical_type and src_label == canonical_label:
            return

        stats.label_or_type_mismatches += 1
        stats.mismatch_rows.append((src_node_id, canonical_id, src_type, canonical_type, src_label, canonical_label))
        logger.warning(
            f"Label/type mismatch merging {src_node_id} ({source_name}) into "
            f"{canonical_id}: type '{src_type}' vs '{canonical_type}', "
            f"label '{src_label}' vs '{canonical_label}' - keeping canonical values"
        )
        if src_type != canonical_type:
            node_property_rows.append((canonical_id, f"alt_type:{source_name}", src_type, "string"))
        if src_label != canonical_label:
            node_property_rows.append((canonical_id, f"alt_label:{source_name}", src_label, "string"))

    def _flush_nodes(
        self,
        node_batch: List[Tuple[str, str, str]],
        identifier_batch: List[Tuple[str, str, str]],
        node_property_rows: List[Tuple[str, str, str, str]],
    ):
        cursor = self.db.cursor
        assert cursor is not None
        if node_batch:
            cursor.executemany("INSERT OR IGNORE INTO nodes (node_id, type, label) VALUES (?, ?, ?)", node_batch)
        if identifier_batch:
            cursor.executemany(
                "INSERT OR IGNORE INTO identifiers (node_id, identifier_type, identifier_value) VALUES (?, ?, ?)",
                identifier_batch,
            )
        for node_id, key, value, value_type in node_property_rows:
            property_id = self._get_or_create_property_id(key, value, value_type)
            cursor.execute(
                "INSERT OR IGNORE INTO node_properties (node_id, property_id) VALUES (?, ?)", (node_id, property_id)
            )

    def _copy_node_properties_for_source(self, src_conn: sqlite3.Connection, source: SourceSpec):
        node_map = self._node_id_map[source.name]
        cursor = self.db.cursor
        assert cursor is not None
        batch: List[Tuple[str, int]] = []
        for node_id, key, value, value_type in src_conn.execute(
            "SELECT np.node_id, p.property_key, p.property_value, p.value_type "
            "FROM node_properties np JOIN properties p ON p.property_id = np.property_id"
        ):
            canonical_id: str = node_map[node_id] if node_id in node_map else node_id
            property_id = self._get_or_create_property_id(key, value, value_type)
            batch.append((canonical_id, property_id))
            if len(batch) >= _BATCH_SIZE:
                cursor.executemany("INSERT OR IGNORE INTO node_properties (node_id, property_id) VALUES (?, ?)", batch)
                batch = []
        if batch:
            cursor.executemany("INSERT OR IGNORE INTO node_properties (node_id, property_id) VALUES (?, ?)", batch)

    def _get_or_create_property_id(self, key: str, value: str, value_type: str) -> int:
        cache_key = (key, value, value_type)
        property_id = self._property_index.get(cache_key)
        if property_id is not None:
            return property_id

        cursor = self.db.cursor
        assert cursor is not None
        property_id = self._next_property_id
        self._next_property_id += 1
        cursor.execute(
            "INSERT INTO properties (property_id, property_key, property_value, value_type) VALUES (?, ?, ?, ?)",
            (property_id, key, value, value_type),
        )
        self._property_index[cache_key] = property_id
        return property_id

    # ------------------------------------------------------------------
    # Pass 2: edges
    # ------------------------------------------------------------------

    def _copy_edges_for_source(self, source: SourceSpec):
        stats = self.stats[source.name]
        cursor = self.db.cursor
        assert cursor is not None
        node_map = self._node_id_map[source.name]

        src_conn = _open_source(source.path)
        try:
            edge_id_map: Dict[int, int] = {}
            batch: List[Tuple[int, str, str, str, Optional[str]]] = []

            for src_edge_id, source_node_id, predicate, target_node_id, sab in src_conn.execute(
                "SELECT edge_id, source_node_id, predicate, target_node_id, sab FROM edges"
            ):
                new_edge_id = self._next_edge_id
                self._next_edge_id += 1
                edge_id_map[src_edge_id] = new_edge_id

                new_source: str = node_map[source_node_id] if source_node_id in node_map else source_node_id
                new_target: str = node_map[target_node_id] if target_node_id in node_map else target_node_id
                batch.append((new_edge_id, new_source, predicate, new_target, sab))
                stats.edges_copied += 1

                if len(batch) >= _BATCH_SIZE:
                    self._insert_edge_batch(batch)
                    batch = []

                if stats.edges_copied % _PROGRESS_EVERY == 0:
                    logger.info(f"  ... {stats.edges_copied} edges processed from '{source.name}'")

            self._insert_edge_batch(batch)
            self._commit()

            self._copy_edge_properties_for_source(src_conn, edge_id_map)
            self._commit()
        finally:
            src_conn.close()

    def _insert_edge_batch(self, batch: List[Tuple[int, str, str, str, Optional[str]]]):
        if not batch:
            return
        cursor = self.db.cursor
        assert cursor is not None
        cursor.executemany(
            "INSERT INTO edges (edge_id, source_node_id, predicate, target_node_id, sab) VALUES (?, ?, ?, ?, ?)",
            batch,
        )

    def _copy_edge_properties_for_source(self, src_conn: sqlite3.Connection, edge_id_map: Dict[int, int]):
        cursor = self.db.cursor
        assert cursor is not None
        batch: List[Tuple[int, int]] = []
        for src_edge_id, key, value, value_type in src_conn.execute(
            "SELECT ep.edge_id, p.property_key, p.property_value, p.value_type "
            "FROM edge_properties ep JOIN properties p ON p.property_id = ep.property_id"
        ):
            new_edge_id = edge_id_map.get(src_edge_id)
            if new_edge_id is None:
                continue
            property_id = self._get_or_create_property_id(key, value, value_type)
            batch.append((new_edge_id, property_id))
            if len(batch) >= _BATCH_SIZE:
                cursor.executemany("INSERT OR IGNORE INTO edge_properties (edge_id, property_id) VALUES (?, ?)", batch)
                batch = []
        if batch:
            cursor.executemany("INSERT OR IGNORE INTO edge_properties (edge_id, property_id) VALUES (?, ?)", batch)

    # ------------------------------------------------------------------
    # Debug db + summary
    # ------------------------------------------------------------------

    def _write_debug_db(self):
        """Persist the node-merge mapping and mismatch/ambiguous-match details to a
        separate SQLite file (its own plain connection - no ATTACH needed)."""
        assert self.debug_db_path is not None
        Path(self.debug_db_path).parent.mkdir(parents=True, exist_ok=True)
        debug_conn = sqlite3.connect(self.debug_db_path)
        try:
            debug_conn.execute("""
                CREATE TABLE IF NOT EXISTS node_id_map (
                    source_name TEXT NOT NULL,
                    src_node_id TEXT NOT NULL,
                    canonical_node_id TEXT NOT NULL,
                    PRIMARY KEY (source_name, src_node_id)
                )
            """)
            debug_conn.execute("DELETE FROM node_id_map")
            for source in self.sources:
                rows = [
                    (source.name, src_id, canonical_id)
                    for src_id, canonical_id in self._node_id_map[source.name].items()
                ]
                debug_conn.executemany("INSERT INTO node_id_map VALUES (?, ?, ?)", rows)

            debug_conn.execute("""
                CREATE TABLE IF NOT EXISTS label_type_mismatches (
                    source_name TEXT NOT NULL,
                    src_node_id TEXT NOT NULL,
                    canonical_node_id TEXT NOT NULL,
                    src_type TEXT,
                    canonical_type TEXT,
                    src_label TEXT,
                    canonical_label TEXT
                )
            """)
            debug_conn.execute("DELETE FROM label_type_mismatches")
            for source in self.sources:
                stats = self.stats[source.name]
                debug_conn.executemany(
                    "INSERT INTO label_type_mismatches VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(source.name, *row) for row in stats.mismatch_rows],
                )

            debug_conn.execute("""
                CREATE TABLE IF NOT EXISTS ambiguous_matches (
                    source_name TEXT NOT NULL,
                    src_node_id TEXT NOT NULL,
                    distinct_canonical_match_count INTEGER NOT NULL,
                    chosen_canonical_node_id TEXT NOT NULL
                )
            """)
            debug_conn.execute("DELETE FROM ambiguous_matches")
            for source in self.sources:
                stats = self.stats[source.name]
                debug_conn.executemany(
                    "INSERT INTO ambiguous_matches VALUES (?, ?, ?, ?)",
                    [(source.name, *row) for row in stats.ambiguous_rows],
                )

            debug_conn.commit()
        finally:
            debug_conn.close()

    def _log_summary(self):
        logger.info("=== Merge summary ===")
        total_added = 0
        total_merged = 0
        total_edges = 0
        for source in self.sources:
            s = self.stats[source.name]
            logger.info(
                f"  {s.source_name}: read={s.nodes_read} merged_into_existing={s.nodes_merged} "
                f"added_as_new={s.nodes_added} ambiguous={s.ambiguous_matches} "
                f"label_or_type_mismatches={s.label_or_type_mismatches} edges_copied={s.edges_copied}"
            )
            total_added += s.nodes_added
            total_merged += s.nodes_merged
            total_edges += s.edges_copied
        logger.info(
            f"  TOTAL: {total_added} canonical nodes, {total_merged} nodes merged into existing ones, "
            f"{total_edges} edges copied"
        )



