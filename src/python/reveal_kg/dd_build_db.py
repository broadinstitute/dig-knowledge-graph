"""
Build SQLite database from downloaded CFDE data files.

This module provides the DataBuilder class for high-level data loading from CSV files.
Database management is handled by kg_database.DatabaseManager.
"""

import csv
import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from kg_database import DatabaseManager

logger = logging.getLogger(__name__)


class DataBuilder:
    """Build knowledge graph data from CSV files into database."""

    def __init__(self, database_manager: DatabaseManager):
        """
        Initialize the data builder.

        Args:
            database_manager: DatabaseManager instance to use for operations
        """
        self.db = database_manager
        self.xref_config, self.xref_exclude = self._load_xref_config()

    def _load_xref_config(self):
        """
        Load and parse xref processing and exclusion configuration.
        
        Returns tuple of (processing_map, exclude_map):
            - processing_map: dict mapping (sab, source) -> processing_config
            - exclude_map: dict mapping sab -> list of sources to exclude
        """
        config_file = Path(__file__).parent / "dd_config.json"
        processing_map = {}
        exclude_map = {}
        
        if config_file.exists():
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                    logger.debug(f"Loaded xref config from {config_file}")
                    
                    # Build lookup map: (sab, source) -> processing_config
                    for rule in config.get('xref_processing', []):
                        proc_type = rule.get('type')
                        sources_by_sab = rule.get('sources', {})
                        
                        for sab, source_list in sources_by_sab.items():
                            for source in source_list:
                                key = (sab, source)
                                processing_map[key] = {
                                    'type': proc_type,
                                    'description': rule.get('description', '')
                                }
                    
                    logger.debug(f"Built processing map with {len(processing_map)} rules")
                    
                    # Load xref exclusions: sab -> list of sources to skip
                    exclude_config = config.get('xref_exclude', {})
                    for sab, sources in exclude_config.items():
                        if isinstance(sources, list):
                            exclude_map[sab] = [s.strip() for s in sources]
                    
                    if exclude_map:
                        logger.debug(f"Loaded xref exclusions: {exclude_map}")
            except Exception as e:
                logger.warning(f"Failed to load xref config: {e}")
        
        return processing_map, exclude_map

    def _process_xref_value(self, sab: Optional[str], source: str, value: str):
        """
        Process xref value based on configuration.
        
        Args:
            sab: The SAB/source name from filename (e.g., 'SPARC', 'NPO'), or None if not detected
            source: The xref source name (e.g., 'UBERON', 'FMA')
            value: The xref value to process
            
        Returns:
            Processed xref value
        """
        if not sab:
            return value
        
        key = (sab, source)
        if key not in self.xref_config:
            return value
        
        config = self.xref_config[key]
        proc_type = config.get('type')
        
        if proc_type == 'remove_decimal':
            # Remove .0 suffix from decimal numbers (e.g., "916.0" -> "916")
            try:
                if '.' in str(value):
                    float_val = float(value)
                    int_val = int(float_val)
                    
                    # Warn if there's a non-zero decimal part
                    if float_val != int_val:
                        logger.warning(f"Decimal value for {sab}/{source}: {value} (non-zero decimal)")
                    
                    return str(int_val)
            except (ValueError, TypeError):
                # Not a numeric value, return as-is
                pass
        
        return value

    def _add_edge_property(self, edge_id: int, property_key: str, property_value: str):
        """Add a property to an edge."""
        assert self.db.cursor is not None and self.db.conn is not None
        try:
            # Insert or get property
            self.db.cursor.execute("""
                INSERT OR IGNORE INTO properties (property_key, property_value, value_type)
                VALUES (?, ?, 'string')
            """, (property_key, property_value))
            
            # Get the property_id
            self.db.cursor.execute("""
                SELECT property_id FROM properties
                WHERE property_key = ? AND property_value = ? AND value_type = 'string'
            """, (property_key, property_value))
            
            property_id = self.db.cursor.fetchone()
            if property_id:
                property_id = property_id[0]
                # Link edge to property
                self.db.cursor.execute("""
                    INSERT OR IGNORE INTO edge_properties (edge_id, property_id)
                    VALUES (?, ?)
                """, (edge_id, property_id))
        except sqlite3.Error as e:
            logger.warning(f"Failed to add edge property {property_key}={property_value}: {e}")

    def load_folder(self, folder_path: str):
        """
        Load all CSV data from a folder into the database.
        
        Assumes database is already initialized and connected.

        Args:
            folder_path: Path to folder containing CSV files
        """
        folder = Path(folder_path)
        if not folder.exists():
            logger.error(f"Folder not found: {folder_path}")
            raise FileNotFoundError(f"Folder not found: {folder_path}")

        logger.info(f"Loading data from folder: {folder_path}")

        # Find all CSV files matching patterns
        node_files = sorted(folder.glob("**/*.nodes.csv"))
        edge_files = sorted(folder.glob("**/*.edges.csv"))

        if not node_files and not edge_files:
            logger.warning(f"No CSV files found in {folder_path}")
            return

        # Load node files (which include xrefs in columns 4+)
        for csv_file in node_files:
            logger.info(f"Loading nodes and xrefs from {csv_file}")
            self._load_nodes_from_file(str(csv_file))

        # Load edge files
        for csv_file in edge_files:
            logger.info(f"Loading edges from {csv_file}")
            self._load_edges_from_file(str(csv_file))

        logger.info("Data loading completed")

    def _load_nodes_from_file(self, csv_path: str):
        """
        Load nodes from a CSV file with header validation.

        Args:
            csv_path: Path to the CSV file
        """
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter by reading first line
                first_line = f.readline()
                f.seek(0)
                
                # Determine delimiter: tab or comma
                delimiter = '\t' if '\t' in first_line else ','
                logger.debug(f"Detected delimiter: {repr(delimiter)} in {csv_path}")
                
                # Read and validate the header line
                reader = csv.reader(f, delimiter=delimiter)
                header_row = next(reader)
                
                # Validate header and get configuration
                header_config = self._validate_node_file_header(header_row, csv_path)
                if not header_config:
                    logger.error(f"Skipping file {csv_path} due to invalid header")
                    return
                
                fieldnames = header_config['fieldnames']
                from_filename = header_config['from_filename']
                file_type = header_config.get('file_type')
                
                # Create DictReader from current position (after header line)
                dict_reader = csv.DictReader(f, fieldnames=fieldnames, delimiter=delimiter)
                self._load_nodes(dict_reader, csv_path, fieldnames, from_filename, file_type)

        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_nodes(self, reader, csv_path: str, fieldnames: Optional[list] = None, 
                    from_filename: bool = False, file_type: Optional[str] = None):
        """
        Load nodes and identifiers from CSV reader.
        
        Only nodes with at least one identifier are stored in the database.
        
        Args:
            reader: CSV DictReader
            csv_path: Path to CSV file (for logging)
            fieldnames: List of actual column names (columns 3+ are identifier types)
            from_filename: If True, type column is filled from filename
            file_type: The node type extracted from filename (when from_filename=True)
        """
        count = 0
        identifier_count = 0
        nodes_skipped = 0  # Track nodes with no identifiers
        verbose = logger.isEnabledFor(logging.DEBUG)
        null_type_warned = False  # Track if we've warned about NULL types in this file
        
        # Extract SAB from filename (e.g., "SPARC.Anatomy.nodes.csv" -> "SPARC")
        filename = Path(csv_path).name
        sab = filename.split('.')[0] if '.' in filename else None
        logger.debug(f"Extracted SAB from filename '{filename}': {sab}")

        assert self.db.cursor is not None and self.db.conn is not None
        try:
            # Use passed fieldnames or get from reader
            if fieldnames is None:
                fieldnames = reader.fieldnames
            logger.debug(f"CSV columns in {csv_path}: {fieldnames}")
            
            # Columns after node_id and label are identifier type columns
            # Format 1: [node_id, label, type, id1, id2, ...] -> identifiers are columns 3+
            # Format 2: [node_id, label, id1, id2, ...] -> identifiers are columns 2+
            if from_filename:
                # Format 2: no type column in CSV, start identifiers at column 2
                identifier_types = fieldnames[2:] if fieldnames and len(fieldnames) > 2 else []
            else:
                # Format 1: type column present, start identifiers at column 3
                identifier_types = fieldnames[3:] if fieldnames and len(fieldnames) > 3 else []
            
            for row_num, row in enumerate(reader, 1):
                if row_num <= 3:
                    logger.debug(f"Row {row_num}: {dict(row)}")
                    
                # Get node data from first 2-3 columns (type may not exist in Format 2)
                # Format 1: [node_id, label, type, ...]
                # Format 2: [node_id, label, ...] (type from filename)
                node_id = (row.get('node_id') or '').strip()
                # Try both 'name' and 'label' column names (handle None values)
                label = ((row.get('name') or '') or (row.get('label') or '')).strip()
                # Type may not exist in Format 2 (alternative format), handle None
                node_type = (row.get('type') or '').strip()

                # Skip rows with empty node_id (including accidental header rows)
                if not node_id:
                    logger.debug(f"Skipping row {row_num}: empty node_id")
                    continue

                # Use node_id as fallback if label is empty (label is NOT NULL in schema)
                if not label:
                    label = node_id
                
                # Handle node type: from file, from filename, or NULL
                if from_filename:
                    # Use type extracted from filename
                    node_type = file_type if file_type else ''
                elif not node_type:
                    # NULL type in CSV: use empty string and warn once per file
                    if not null_type_warned:
                        logger.warning(f"Found NULL node types in {filename} - using empty string")
                        null_type_warned = True
                    node_type = ''

                # Collect identifiers first to determine if node should be stored
                # Parse identifiers from columns 3+ (Format 1) or 2+ (Format 2)
                # Column header is identifier type (UBERON, FMA, etc.), value is the identifier
                node_identifiers = []
                for identifier_type in identifier_types:
                    # Check if this type should be excluded for this SAB
                    if sab in self.xref_exclude and identifier_type in self.xref_exclude[sab]:
                        logger.debug(f"Skipping identifier type '{identifier_type}' for SAB '{sab}' (excluded)")
                        continue
                    
                    # Handle None values from missing columns (use empty string as default)
                    identifier_value = (row.get(identifier_type) or '').strip()
                    if identifier_value:
                        # Apply processing if configured for this SAB + identifier_type combination
                        processed_value = self._process_xref_value(sab, identifier_type, identifier_value)
                        
                        # Store as CURIE format: {identifier_type}:{identifier_value}
                        curie_value = f"{identifier_type}:{processed_value}"
                        node_identifiers.append((identifier_type, curie_value))
                
                # Only insert node if it has at least one identifier
                if not node_identifiers:
                    logger.debug(f"Row {row_num}: Skipping node {node_id} - no identifiers found")
                    nodes_skipped += 1
                    continue
                
                # Insert node with new schema column order (node_id, type, label)
                self.db.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, type, label)
                    VALUES (?, ?, ?)
                """, (node_id, node_type, label))
                
                # Commit after each node only in verbose mode
                if verbose:
                    self.db.conn.commit()
                
                count += 1
                
                # Insert collected identifiers
                for identifier_type, curie_value in node_identifiers:
                    self.db.cursor.execute("""
                        INSERT OR IGNORE INTO identifiers (node_id, identifier_type, identifier_value)
                        VALUES (?, ?, ?)
                    """, (node_id, identifier_type, curie_value))
                    identifier_count += 1

            # Final commit after all rows (only needed if not in verbose mode)
            if not verbose:
                self.db.conn.commit()
            
            if nodes_skipped > 0:
                logger.info(f"Loaded {count} nodes and {identifier_count} identifiers from {csv_path} "
                           f"(skipped {nodes_skipped} nodes with no identifiers)")
            else:
                logger.info(f"Loaded {count} nodes and {identifier_count} identifiers from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load nodes: {e}")
            self.db.conn.rollback()
            raise

    def _validate_node_file_header(self, header_row: list, csv_path: str) -> Optional[dict]:
        """
        Validate node file header and determine format.
        
        Supports two formats:
        1. Standard: empty/id, label, type, identifier_types...
           - Columns 0: node_id, 1: label, 2: type, 3+: identifier types
        2. Alternative: id, label, identifier_types... (no type)
           - Columns 0: node_id, 1: label, 2+: identifier types
           - Type is extracted from filename: <SAB>.<Type>.nodes.csv
        
        Args:
            header_row: List of header column names
            csv_path: Path to the file (for filename extraction)
        
        Returns:
            Dict with keys: fieldnames, type_column_index, or None if invalid
        """
        if not header_row or len(header_row) < 2:
            logger.error(f"Invalid header in {csv_path}: too few columns. Expected at least (id/empty, label, ...)")
            return None
        
        # Normalize first column (empty string or 'id' both mean node_id)
        first_col = header_row[0].strip().lower()
        is_id_first = first_col == '' or first_col == 'id'
        second_col = header_row[1].strip().lower() if len(header_row) > 1 else ''
        third_col = header_row[2].strip().lower() if len(header_row) > 2 else ''
        
        # Check if second column is 'label'
        if second_col != 'label':
            logger.error(f"Invalid header in {csv_path}: expected 'label' in column 2, got '{header_row[1]}'")
            return None
        
        # Determine format based on third column
        if third_col == 'type' or (third_col == '' and len(header_row) > 3):
            # Standard format: id/empty, label, type, identifier_types...
            if not is_id_first:
                logger.error(f"Invalid header in {csv_path}: first column should be empty or 'id', got '{header_row[0]}'")
                return None
            
            return {
                'fieldnames': ['node_id', 'label', 'type'] + header_row[3:],
                'type_column_index': 2,
                'from_filename': False
            }
        else:
            # Alternative format: id, label, identifier_types... (no type)
            # Extract type from filename: <SAB>.<Type>.nodes.csv
            if not is_id_first:
                logger.error(f"Invalid header in {csv_path}: first column should be empty or 'id', got '{header_row[0]}'")
                return None
            
            filename = Path(csv_path).name
            # Parse filename: SAB.Type.nodes.csv
            parts = filename.replace('.nodes.csv', '').split('.')
            if len(parts) < 2:
                logger.error(f"Invalid filename format in {csv_path}: expected '<SAB>.<Type>.nodes.csv'")
                return None
            
            file_type = parts[1]  # Type is second part (after SAB)
            
            return {
                'fieldnames': ['node_id', 'label'] + header_row[2:],  # No 'type' column in CSV for this format
                'type_column_index': -1,  # Sentinel: type comes from filename
                'from_filename': True,
                'file_type': file_type
            }

    def _load_edges_from_file(self, csv_path: str):
        """
        Load edges from a CSV file with validation.
        
        Args:
            csv_path: Path to the edges CSV file
        """
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter
                first_line = f.readline()
                f.seek(0)
                delimiter = '\t' if '\t' in first_line else ','
                
                # Extract expected SAB from filename (e.g., "SPARC.edges.csv" -> "SPARC")
                filename = Path(csv_path).name
                expected_sab = filename.split('.')[0] if '.' in filename else None
                logger.debug(f"Expected SAB from filename '{filename}': {expected_sab}")
                
                reader = csv.DictReader(f, delimiter=delimiter)
                
                # Validate required columns exist
                required_cols = ['source', 'target']
                if reader.fieldnames and not all(col in reader.fieldnames for col in required_cols):
                    raise ValueError(
                        f"Missing required columns in {csv_path}. "
                        f"Expected: {required_cols}, Found: {reader.fieldnames}"
                    )
                
                self._load_edges(reader, csv_path, expected_sab)
        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_edges(self, reader, csv_path: str, expected_sab: Optional[str] = None):
        """Load edges from CSV reader with SAB validation and property handling.
        
        Only creates edges if both source and target nodes exist in the database.
        """
        count = 0
        sab_mismatch_count = 0
        skipped_count = 0
        missing_nodes_count = 0
        sab_mismatch_warned = False
        assert self.db.cursor is not None and self.db.conn is not None
        try:
            for row_num, row in enumerate(reader, 1):
                # First ensure source and target nodes exist
                source = row.get('source', '').strip()
                target = row.get('target', '').strip()
                
                # Handle both 'SAB' and 'sab' (case-insensitive)
                sab = row.get('SAB', '') or row.get('sab', '')
                sab = sab.strip()

                # Skip rows with empty source or target
                if not source or not target:
                    logger.debug(
                        f"Row {row_num} in {csv_path}: Skipping edge with empty "
                        f"source={repr(source)} or target={repr(target)}"
                    )
                    skipped_count += 1
                    continue

                # Verify SAB matches filename if expected_sab is provided
                # Use filename SAB if there's a mismatch, and warn only once per file
                if expected_sab and sab and sab != expected_sab:
                    if not sab_mismatch_warned:
                        logger.warning(
                            f"Row {row_num} in {csv_path}: SAB mismatch - "
                            f"filename expects '{expected_sab}' but row has '{sab}'. "
                            f"Using filename value '{expected_sab}' for all mismatches in this file."
                        )
                        sab_mismatch_warned = True
                    sab = expected_sab
                    sab_mismatch_count += 1

                # Check if both source and target nodes exist in the database
                self.db.cursor.execute("SELECT 1 FROM nodes WHERE node_id = ?", (source,))
                source_exists = self.db.cursor.fetchone() is not None
                
                self.db.cursor.execute("SELECT 1 FROM nodes WHERE node_id = ?", (target,))
                target_exists = self.db.cursor.fetchone() is not None
                
                # Skip edge if either node doesn't exist
                if not source_exists or not target_exists:
                    logger.debug(
                        f"Row {row_num} in {csv_path}: Skipping edge - "
                        f"source {repr(source)} exists={source_exists}, "
                        f"target {repr(target)} exists={target_exists}"
                    )
                    missing_nodes_count += 1
                    continue

                # Insert edge with new column names
                # Handle case-insensitive column names for relation, evidence_class, dcc
                relation = (row.get('relation', '') or row.get('Relation', '')).strip()
                
                self.db.cursor.execute("""
                    INSERT INTO edges (source_node_id, predicate, target_node_id, sab)
                    VALUES (?, ?, ?, ?)
                """, (
                    source,
                    relation,
                    target,
                    sab
                ))
                
                edge_id = self.db.cursor.lastrowid
                if edge_id is None:
                    logger.warning(f"Failed to insert edge for row {row_num} in {csv_path}")
                    continue
                count += 1
                
                # Store evidence_class and dcc as edge properties (case-insensitive)
                evidence_class = (row.get('evidence_class', '') or row.get('evidence_Class', '') or row.get('Evidence_Class', '')).strip()
                dcc = (row.get('dcc', '') or row.get('DCC', '')).strip()
                
                if evidence_class:
                    self._add_edge_property(edge_id, 'evidence_class', evidence_class)
                
                if dcc:
                    self._add_edge_property(edge_id, 'dcc', dcc)

            self.db.conn.commit()
            
            # Report skip reasons
            skip_reasons = []
            if skipped_count > 0:
                skip_reasons.append(f"{skipped_count} rows with empty source/target")
            if missing_nodes_count > 0:
                skip_reasons.append(f"{missing_nodes_count} edges with missing nodes")
            if sab_mismatch_count > 0:
                skip_reasons.append(f"{sab_mismatch_count} SAB mismatches with filename")
            
            if skip_reasons:
                logger.warning(f"Loaded {count} edges from {csv_path} (skipped: {', '.join(skip_reasons)})")
            else:
                logger.info(f"Loaded {count} edges from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load edges: {e}")
            self.db.conn.rollback()
            raise

    def _create_indexes(self):
        """
        Create query performance indexes from kg_indexes.sql file.
        Call this after data loading is complete for optimal query performance.
        """
        assert self.db.cursor is not None and self.db.conn is not None
        try:
            index_file = Path(__file__).parent.parent.parent / "sql" / "kg_indexes.sql"
            if not index_file.exists():
                logger.warning(f"Index file not found: {index_file}")
                return
            
            with open(index_file, 'r') as f:
                index_sql = f.read()
            
            logger.info("Creating query performance indexes...")
            # Execute all statements in the index file
            for statement in index_sql.split(';'):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    self.db.cursor.execute(statement)
            
            self.db.conn.commit()
            logger.info("Query performance indexes created successfully")
        except Exception as e:
            logger.error(f"Failed to create indexes: {e}")
            raise


# For backwards compatibility, export both classes
__all__ = ['DatabaseManager', 'DataBuilder']
