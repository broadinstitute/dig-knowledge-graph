"""
Build SQLite database from downloaded CFDE data files.

This module creates and populates a SQLite database with nodes, edges, identifiers, and properties tables.
Uses the new normalized schema (kg_schema.sql).
"""

import csv
import json
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DatabaseBuilder:
    """Build SQLite database from CFDE data files."""

    def __init__(self, db_path: str = "data/ddkg.sqlite", force_clean_db: bool = False):
        """
        Initialize the database builder.

        Args:
            db_path: Path to the SQLite database file
            force_clean_db: If True, delete existing database before building
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.force_clean_db = force_clean_db
        self.conn = None
        self.cursor = None
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
            # Remove .0 suffix if present, warn if decimal part is not exactly .0
            if isinstance(value, str) and '.' in value:
                try:
                    num_val = float(value)
                    # Check if it's a whole number
                    if num_val == int(num_val):
                        return str(int(num_val))
                    else:
                        # Non-zero decimal part - warn but keep value
                        logger.warning(
                            f"Xref {sab}:{source} has non-zero decimal: {value} "
                            f"(expected integer, keeping as-is)"
                        )
                except (ValueError, TypeError):
                    pass  # Not numeric, keep original
        
        return value

    def _add_edge_property(self, edge_id: int, property_key: str, property_value: str):
        """
        Add a property to an edge (stores in properties + edge_properties tables).
        
        Args:
            edge_id: ID of the edge
            property_key: Property name (e.g., 'evidence_class', 'dcc')
            property_value: Property value
        """
        try:
            # Insert or get the property (deduplicated by key, value, and type)
            self.cursor.execute("""
                INSERT OR IGNORE INTO properties (property_key, property_value, value_type)
                VALUES (?, ?, 'string')
            """, (property_key, property_value))
            
            # Get the property_id
            self.cursor.execute("""
                SELECT property_id FROM properties
                WHERE property_key = ? AND property_value = ? AND value_type = 'string'
            """, (property_key, property_value))
            
            property_id = self.cursor.fetchone()
            if property_id:
                property_id = property_id[0]
                # Link edge to property
                self.cursor.execute("""
                    INSERT OR IGNORE INTO edge_properties (edge_id, property_id)
                    VALUES (?, ?)
                """, (edge_id, property_id))
        except sqlite3.Error as e:
            logger.warning(f"Failed to add edge property {property_key}={property_value}: {e}")

    def connect(self):
        """Connect to the database."""
        try:
            # Remove old database file if force_clean_db is True
            if self.force_clean_db and self.db_path.exists():
                self.db_path.unlink()
                logger.info(f"Removed old database: {self.db_path}")
            
            self.conn = sqlite3.connect(str(self.db_path))
            self.cursor = self.conn.cursor()
            # Enable foreign keys
            self.cursor.execute("PRAGMA foreign_keys = ON")
            logger.info(f"Connected to database: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    def disconnect(self):
        """Disconnect from the database."""
        if self.conn:
            self.conn.close()
            logger.info("Disconnected from database")

    def create_schema(self):
        """Create database schema from SQL file."""
        try:
            logger.info("Creating database schema...")

            # Read and execute schema file (new normalized schema)
            # Path: src/sql/kg_schema.sql
            schema_file = Path(__file__).parent.parent.parent / "sql" / "kg_schema.sql"
            
            if not schema_file.exists():
                logger.error(f"Schema file not found: {schema_file}")
                raise FileNotFoundError(f"Schema file not found: {schema_file}")

            with open(schema_file, 'r') as f:
                schema_sql = f.read()

            # Execute all statements in the schema file
            self.cursor.executescript(schema_sql)
            self.conn.commit()
            logger.info("Database schema created successfully")

        except sqlite3.Error as e:
            logger.error(f"Failed to create schema: {e}")
            raise

    def load_data_from_folder(self, folder_path: str):
        """
        Load data from CSV files in a folder.

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
            self._load_csv_file(str(csv_file), 'nodes')

        # Load edge files
        for csv_file in edge_files:
            logger.info(f"Loading edges from {csv_file}")
            self._load_edges_from_file(str(csv_file))

        logger.info("Data loading completed")

    def _load_csv_file(self, csv_path: str, table_name: str):
        """
        Load a CSV file into the database.

        Args:
            csv_path: Path to the CSV file
            table_name: Name of the table ('nodes' or 'edges')
        """
        try:
            with open(csv_path, 'r', encoding='utf-8') as f:
                # Detect delimiter by reading first line
                first_line = f.readline()
                f.seek(0)
                
                # Determine delimiter: tab or comma
                delimiter = '\t' if '\t' in first_line else ','
                logger.debug(f"Detected delimiter: {repr(delimiter)} in {csv_path}")
                
                if table_name == 'nodes':
                    # For nodes, read the header line to get actual column names
                    reader = csv.reader(f, delimiter=delimiter)
                    header_row = next(reader)
                    # File position is now after the header line - don't seek back!
                    
                    # First column has no header, so prepend 'node_id'
                    if header_row and header_row[0] == '':
                        fieldnames = ['node_id'] + header_row[1:]
                    else:
                        # If first column has a name, still use 'node_id' for consistency
                        fieldnames = ['node_id'] + header_row[1:] if header_row[0] else ['node_id'] + header_row
                    
                    # Create DictReader from current position (after header line)
                    dict_reader = csv.DictReader(f, fieldnames=fieldnames, delimiter=delimiter)
                    self._load_nodes(dict_reader, csv_path, fieldnames)
                else:
                    logger.warning(f"Unknown table: {table_name}")

        except Exception as e:
            logger.error(f"Failed to load {csv_path}: {e}")
            raise

    def _load_nodes(self, reader, csv_path: str, fieldnames: Optional[list] = None):
        """
        Load nodes and identifiers from CSV reader.
        
        Args:
            reader: CSV DictReader
            csv_path: Path to CSV file (for logging)
            fieldnames: List of actual column names (columns 3+ are identifier types)
        """
        count = 0
        identifier_count = 0
        verbose = logger.isEnabledFor(logging.DEBUG)
        null_type_warned = False  # Track if we've warned about NULL types in this file
        
        # Extract SAB from filename (e.g., "SPARC.Anatomy.nodes.csv" -> "SPARC")
        filename = Path(csv_path).name
        sab = filename.split('.')[0] if '.' in filename else None
        logger.debug(f"Extracted SAB from filename '{filename}': {sab}")
        
        try:
            # Use passed fieldnames or get from reader
            if fieldnames is None:
                fieldnames = reader.fieldnames
            logger.debug(f"CSV columns in {csv_path}: {fieldnames}")
            
            # Columns 3+ are identifier type columns (header = identifier type like UBERON, FMA)
            identifier_types = fieldnames[3:] if fieldnames and len(fieldnames) > 3 else []
            
            for row_num, row in enumerate(reader, 1):
                if row_num <= 3:
                    logger.debug(f"Row {row_num}: {dict(row)}")
                    
                # Get node data from first 3 columns
                # Column 1 is node_id, column 2 is name/label, column 3 is type
                node_id = row.get('node_id', '').strip()
                # Try both 'name' and 'label' column names
                label = row.get('name', '') or row.get('label', '')
                label = label.strip()
                node_type = row.get('type', '').strip()

                # Skip rows with empty node_id (including accidental header rows)
                if not node_id:
                    logger.debug(f"Skipping row {row_num}: empty node_id")
                    continue

                # Use node_id as fallback if label is empty (label is NOT NULL in schema)
                if not label:
                    label = node_id
                
                # Handle NULL types: use empty string and warn once per file
                if not node_type:
                    if not null_type_warned:
                        logger.warning(f"Found NULL node types in {filename} - using empty string")
                        null_type_warned = True
                    node_type = ''

                # Insert node with new schema column order (node_id, type, label)
                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, type, label)
                    VALUES (?, ?, ?)
                """, (node_id, node_type, label))
                
                # Commit after each node only in verbose mode
                if verbose:
                    self.conn.commit()
                
                count += 1

                # Parse identifiers from columns 3+ 
                # Column header is identifier type (UBERON, FMA, etc.), value is the identifier
                for identifier_type in identifier_types:
                    # Check if this type should be excluded for this SAB
                    if sab in self.xref_exclude and identifier_type in self.xref_exclude[sab]:
                        logger.debug(f"Skipping identifier type '{identifier_type}' for SAB '{sab}' (excluded)")
                        continue
                    
                    identifier_value = row.get(identifier_type, '').strip()
                    if identifier_value:
                        # Apply processing if configured for this SAB + identifier_type combination
                        processed_value = self._process_xref_value(sab, identifier_type, identifier_value)
                        
                        # Store as CURIE format: {identifier_type}:{identifier_value}
                        curie_value = f"{identifier_type}:{processed_value}"
                        
                        # Insert identifier
                        self.cursor.execute("""
                            INSERT INTO identifiers (node_id, identifier_type, identifier_value)
                            VALUES (?, ?, ?)
                        """, (node_id, identifier_type, curie_value))
                        identifier_count += 1

            # Final commit after all rows (only needed if not in verbose mode)
            if not verbose:
                self.conn.commit()
            
            logger.info(f"Loaded {count} nodes and {identifier_count} identifiers from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load nodes: {e}")
            self.conn.rollback()
            raise

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
        """Load edges from CSV reader with SAB validation and property handling."""
        count = 0
        sab_mismatch_count = 0
        skipped_count = 0
        try:
            for row_num, row in enumerate(reader, 1):
                # First ensure source and target nodes exist
                source = row.get('source', '').strip()
                target = row.get('target', '').strip()
                sab = row.get('SAB', '').strip()

                # Skip rows with empty source or target
                if not source or not target:
                    logger.debug(
                        f"Row {row_num} in {csv_path}: Skipping edge with empty "
                        f"source={repr(source)} or target={repr(target)}"
                    )
                    skipped_count += 1
                    continue

                # Verify SAB matches filename if expected_sab is provided
                if expected_sab and sab and sab != expected_sab:
                    logger.warning(
                        f"Row {row_num} in {csv_path}: SAB mismatch - "
                        f"filename expects '{expected_sab}' but row has '{sab}'"
                    )
                    sab_mismatch_count += 1

                # Insert placeholder nodes if they don't exist (with new schema columns)
                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, type, label)
                    VALUES (?, ?, ?)
                """, (source, '', source))

                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, type, label)
                    VALUES (?, ?, ?)
                """, (target, '', target))

                # Insert edge with new column names
                self.cursor.execute("""
                    INSERT INTO edges (source_node_id, predicate, target_node_id, sab)
                    VALUES (?, ?, ?, ?)
                """, (
                    source,
                    row.get('relation'),
                    target,
                    sab
                ))
                
                edge_id = self.cursor.lastrowid
                count += 1
                
                # Store evidence_class and dcc as edge properties
                evidence_class = row.get('evidence_class', '').strip()
                dcc = row.get('dcc', '').strip()
                
                if evidence_class:
                    self._add_edge_property(edge_id, 'evidence_class', evidence_class)
                
                if dcc:
                    self._add_edge_property(edge_id, 'dcc', dcc)

            self.conn.commit()
            if skipped_count > 0:
                logger.warning(
                    f"Loaded {count} edges from {csv_path} "
                    f"(skipped {skipped_count} rows with empty source/target)"
                )
            elif sab_mismatch_count > 0:
                logger.warning(
                    f"Loaded {count} edges from {csv_path} "
                    f"({sab_mismatch_count} SAB mismatches with filename)"
                )
            else:
                logger.info(f"Loaded {count} edges from {csv_path}")
        except Exception as e:
            logger.error(f"Failed to load edges: {e}")
            self.conn.rollback()
            raise

    def build(self, data_folder: str):
        """
        Build the database from CSV files.

        Args:
            data_folder: Path to folder containing extracted CSV files
        """
        try:
            self.connect()
            self.create_schema()
            self.load_data_from_folder(data_folder)
            logger.info(f"Database built successfully: {self.db_path}")
        except Exception as e:
            logger.error(f"Failed to build database: {e}")
            sys.exit(1)
        finally:
            self.disconnect()
