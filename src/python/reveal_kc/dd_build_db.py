"""
Build SQLite database from downloaded CFDE data files.

This module creates and populates a SQLite database with nodes, edges, and xref tables.
"""

import csv
import logging
import sqlite3
import sys
from pathlib import Path

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

            # Read and execute schema file
            schema_file = Path(__file__).parent / "ddkg_schema.sql"
            
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

    def _load_nodes(self, reader, csv_path: str, fieldnames: list = None):
        """
        Load nodes and xrefs from CSV reader.
        
        Args:
            reader: CSV DictReader
            csv_path: Path to CSV file (for logging)
            fieldnames: List of actual column names (columns 3+ are xref SABs)
        """
        count = 0
        xref_count = 0
        verbose = logger.isEnabledFor(logging.DEBUG)
        
        try:
            # Use passed fieldnames or get from reader
            if fieldnames is None:
                fieldnames = reader.fieldnames
            logger.debug(f"CSV columns in {csv_path}: {fieldnames}")
            
            # Columns 3+ are xref columns with header = SAB
            xref_sabs = fieldnames[3:] if fieldnames and len(fieldnames) > 3 else []
            
            for row_num, row in enumerate(reader, 1):
                if row_num <= 3:
                    logger.debug(f"Row {row_num}: {dict(row)}")
                    
                # Get node data from first 3 columns
                # Column 1 is node_id, column 2 is name/label, column 3 is type
                node_id = row.get('node_id', '').strip()
                # Try both 'name' and 'label' column names
                name = row.get('name', '') or row.get('label', '')
                name = name.strip()
                node_type = row.get('type', '').strip()

                # Skip rows with empty node_id (including accidental header rows)
                if not node_id:
                    logger.debug(f"Skipping row {row_num}: empty node_id")
                    continue

                # Use node_id as fallback if name is empty (name is NOT NULL in schema)
                if not name:
                    name = node_id

                # Insert node
                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, name, type)
                    VALUES (?, ?, ?)
                """, (node_id, name, node_type if node_type else None))
                
                # Commit after each node only in verbose mode
                if verbose:
                    self.conn.commit()
                
                count += 1

                # Parse xrefs from columns 3+ (column header is SAB, value is id as string)
                for sab in xref_sabs:
                    xref_value = row.get(sab, '').strip()
                    if xref_value:
                        # Insert xref - source is column header (SAB), id is the value (as string, no conversion)
                        self.cursor.execute("""
                            INSERT INTO xref (node_id, source, id)
                            VALUES (?, ?, ?)
                        """, (node_id, sab, xref_value))
                        xref_count += 1

            # Final commit after all rows (only needed if not in verbose mode)
            if not verbose:
                self.conn.commit()
            
            logger.info(f"Loaded {count} nodes and {xref_count} xrefs from {csv_path}")
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

    def _load_edges(self, reader, csv_path: str, expected_sab: str = None):
        """Load edges from CSV reader with SAB validation."""
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

                # Insert placeholder nodes if they don't exist
                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, name, type)
                    VALUES (?, ?, NULL)
                """, (source, source))

                self.cursor.execute("""
                    INSERT OR IGNORE INTO nodes (node_id, name, type)
                    VALUES (?, ?, NULL)
                """, (target, target))

                # Insert edge
                self.cursor.execute("""
                    INSERT INTO edges (source, target, relation, sab, evidence_class, dcc)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    source,
                    target,
                    row.get('relation'),
                    sab,
                    row.get('evidence_class'),
                    row.get('dcc')
                ))
                count += 1

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
