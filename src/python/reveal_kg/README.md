# CFDE REVEAL Knowledge Graph Data Distillery

A Python utility to download, extract, and build SQLite knowledge graph databases from multiple data sources. 

## Supported Knowledge Graphs

Currently supported:
- **Data Distillery Knowledge Graph**: CFDE (Common Fund Data Ecosystem) REVEAL data sources
- **Biomarker Knowledge Graph**: Biomarker-specific CSV data

Future support:
- (Additional knowledge graphs to be integrated)

## Overview

The Data Distillery automates the process of:
1. **Downloading** data files from multiple sources
2. **Extracting** and validating CSV files
3. **Building** SQLite databases with normalized schemas for nodes, edges, and cross-references

Two independent pipelines are provided:
- **CFDE Data Distillery**: Download and build knowledge graph from Common Fund data sources (SPARC, etc.)
- **Biomarker KG Loader**: Load pre-downloaded biomarker CSV data into knowledge graph database

## Components

### Data Distillery Knowledge Graph (CFDE)

#### `data_distillery_kg.py`
Main CLI entry point for downloading and building CFDE knowledge graph database with flexible command-line arguments.

#### `dd_download.py`
Handles downloading and extracting zip files:
- Reads download URLs from `data/DataDistillerySources.tsv` (column 7)
- Downloads files with progress logging
- Extracts zip contents to organized folder structure
- Cleans up partial folders on extraction failure
- Checks if data is already extracted before re-downloading

#### `dd_build_db.py`
Builds SQLite database from CFDE CSV files:
- Auto-detects tab or comma delimiters
- Validates node file headers (supports two formats)
- Loads node data (ID, label, type, and identifiers)
- Loads edge data (source, target, predicate, metadata) - only if both nodes exist in database
- Stores identifiers in CURIE format (e.g., "UBERON:916")
- Extracts SAB (data source) from filename for identifier processing
- Applies configurable identifier processing based on SAB + identifier type (e.g., remove `.0` decimals)
- Only creates nodes with at least one identifier
- Supports batch commits or per-row commits (verbose mode)
- Deduplicates identifiers with UNIQUE constraint

#### `dd_config.json`
Configuration file for special processing of CFDE identifier values:
- Specifies which identifier types (by SAB) need preprocessing
- Currently supports `remove_decimal` type to strip `.0` from numeric identifiers
- Warns if decimal part is non-zero (e.g., `916.5` instead of `916.0`)
- Example: UBERON and FMA identifiers have `.0` suffix in CSV but should be stored as integers
- Also specifies exclusion rules to skip certain identifier types per SAB

### Biomarker Knowledge Graph

#### `biomarker_kg.py`
Loads biomarker-specific CSV data into SQLite database:
- Reads semantic type mappings from `biomarker_config.yaml`
- Generates UUID for each node (consistent with backup database format)
- Stores original identifiers (e.g., "HGNC:1234") in identifiers table
- Maps original node IDs to UUIDs for edge loading
- Uses batch processing for efficient database inserts
- Supports configurable batch size and deduplication settings
- Populates `sab` field with "BIOMARKER" default from config
- Uses config-driven node type mapping (e.g., "HGNC" → "gene", "CHEBI" → "chemical")

#### `biomarker_config.yaml`
Configuration for biomarker data loading:
- **nodes.types**: Map filename prefixes to semantic types (HGNC → gene, CHEBI → chemical, etc.)
- **edges.default_sab**: Default data source abbreviation ("BIOMARKER")
- **loading.batch_size**: Number of rows per batch commit (5000)
- **loading.skip_duplicates**: Skip duplicate node IDs if already loaded

### Shared Components

#### `kg_schema.sql`
Normalized SQLite database schema with seven tables (used by both pipelines):
- **nodes**: node_id (PK), type (NOT NULL), label (NOT NULL)
- **edges**: edge_id (PK auto), source_node_id (FK), predicate (NOT NULL), target_node_id (FK), sab
- **identifiers**: identifier_id (PK auto), node_id (FK), identifier_type, identifier_value (CURIE format, UNIQUE)
- **properties**: property_id (PK auto), property_key, property_value, value_type (UNIQUE)
- **node_properties**: many-to-many join table for nodes and properties
- **edge_properties**: many-to-many join table for edges and properties
- Essential indexes on foreign keys and common query fields

#### `kg_indexes.sql`
Query performance indexes (created after data loading):
- Indexes on edges (source, target, predicate)
- Indexes on properties (lookup by node/edge and by property)
- Indexes on identifiers (lookup by node_id and by type/value)
- Indexes on nodes (lookup by type)

#### `kg_database.py`
Isolated SQLite database lifecycle management (used by both pipelines):
- Connection management with foreign key constraints
- Schema initialization and creation
- Index creation with detailed logging

## Installation

```bash
pip install requests
```

## Usage

### Data Distillery Knowledge Graph (CFDE)

#### Basic: Download and build database (clean)
```bash
python data_distillery_kg.py -O
```
- Downloads all files to `data/DataDistilleryKG/download/`
- Extracts and processes CSVs
- Creates fresh database at `data/DataDistilleryKG/ddkg.sqlite`
- Uses `-O` flag to delete old database

#### Download only (no clean)
```bash
python data_distillery_kg.py -d
```
- Downloads files if not already extracted
- Keeps existing database
- Uses default folders: `data/DataDistilleryKG/download/`

#### Process existing files (no download)
```bash
python data_distillery_kg.py -i data/DataDistilleryKG/download
```
- Skips download entirely
- Processes CSVs from specified folder
- Optionally creates indexes with `-X` flag

#### Force re-download all files
```bash
python data_distillery_kg.py -D -O
```
- Forces download of all files (even if already extracted)
- Cleans database and starts fresh

#### Process all folders with index creation
```bash
python data_distillery_kg.py -I -O
```
- `-I`: Process all folders found in download directory
- Indexes are automatically created after all data loads
- Creates single database from multiple source folders

#### Verbose logging with file output
```bash
python data_distillery_kg.py -O -v -l build.log
```
- `-v`: Show debug output (commits after each node)
- `-l build.log`: Write logs to file
- `-X`: Create indexes after loading (for single-folder builds)

#### Custom output paths
```bash
python data_distillery_kg.py -f data/raw -i data/processed -o mydb.sqlite
```
- `-f data/raw`: Download to `data/raw/`
- `-i data/processed`: Process CSVs from `data/processed/`
- `-o mydb.sqlite`: Create database at `mydb.sqlite`

#### Production build (recommended)
```bash
python data_distillery_kg.py -O -D -I -o data/DataDistilleryKG/CFDE-DD-KG.sqlite -l data/DataDistilleryKG/CFDE-DD-KG.log -X
```
Complete end-to-end build with all features:
- `-O`: Clean/delete old database to start fresh
- `-D`: Force re-download all data files
- `-I`: Process all folders in download directory into single database
- `-o data/DataDistilleryKG/CFDE-DD-KG.sqlite`: Output to production database file
- `-l data/DataDistilleryKG/CFDE-DD-KG.log`: Log all operations to file
- `-X`: Create query indexes after all data loads (improves performance)

### Biomarker Knowledge Graph

#### Basic biomarker loading with clean database
```bash
python biomarker_kg.py -i data/BiomarkerKG -o data/biomarker_kg.sqlite -O
```
- `-i data/BiomarkerKG`: Input folder with `*.nodes.csv` and `*.edges.csv` files
- `-o data/biomarker_kg.sqlite`: Output database file
- `-O`: Delete old database and start fresh

#### With indexes and verbose logging
```bash
python biomarker_kg.py -i data/BiomarkerKG -o data/biomarker_kg.sqlite -O -X -v -l biomarker.log
```
- `-X`: Create query performance indexes after loading
- `-v`: Show debug output and per-batch logging
- `-l biomarker.log`: Write logs to file

#### Production build (recommended)
```bash
python biomarker_kg.py -i data/BiomarkerKG/processed -o data/BiomarkerKG/CFDE_Biomarker_KG.sqlite -O -l data/BiomarkerKG/CFDE_Biomarker_KG.log -X
```
Complete production build with all features:
- `-i data/BiomarkerKG/processed`: Load from processed biomarker data folder
- `-o data/BiomarkerKG/CFDE_Biomarker_KG.sqlite`: Output to production database file
- `-O`: Delete old database and start fresh
- `-l data/BiomarkerKG/CFDE_Biomarker_KG.log`: Log all operations to file
- `-X`: Create query indexes after loading (improves performance)

#### Node Type Mapping (Biomarker KG)

Biomarker nodes are categorized by semantic type based on filename prefix (configured in `biomarker_config.yaml`):

| Prefix | Type | Example |
|--------|------|---------|
| BIOMARKER | biomarker | BIOMARKER.nodes.csv |
| HGNC | gene | HGNC.nodes.csv |
| CHEBI | chemical | CHEBI.nodes.csv |
| DOID | disease | DOID.nodes.csv |
| UNIPROTKB | protein | UNIPROTKB.nodes.csv |
| PR | protein | PR.nodes.csv |
| CL | cell | CL.nodes.csv |
| UBERON | anatomical_structure | UBERON.nodes.csv |

#### Node ID Strategy (Biomarker KG)

Biomarker nodes use **UUID-based identifiers** for compatibility with merge operations:
- Each loaded node gets a unique UUID (e.g., `500d6255-6837-44d6-8010-65e989e0e16b`)
- Original identifiers (e.g., `HGNC:1234`) are stored in the `identifiers` table
- Edges reference nodes by UUID, not original identifier
- This allows proper mapping when merging multiple knowledge graphs

#### CSV Format (Biomarker KG)

**Node Files (*.nodes.csv)**
- **id** or **node_id**: Unique node identifier (e.g., "HGNC:12345" or "CHEBI:15377")
- **label** or **name**: Human-readable node label
- **type** (optional): Node type (overridden by config-driven mapping from filename prefix)

Example (HGNC.nodes.csv):
```
id,label
HGNC:1234,TP53
HGNC:2042,RBM47
```

**Edge Files (*.edges.csv)**
- **source**: Source node identifier (must match loaded node ID)
- **target**: Target node identifier (must match loaded node ID)
- **relation**: Edge predicate/relationship type
- **SAB** (optional): Source authority (defaults to "BIOMARKER" from config)

Example:
```
source,target,relation,SAB
HGNC:1234,CHEBI:15377,associated_with,BIOMARKER
```

## Command-Line Arguments

### Data Distillery Knowledge Graph (data_distillery_kg.py)

| Flag | Long | Description | Default |
|------|------|-------------|---------|
| `-d` | `--download` | Download if not yet extracted | False |
| `-D` | `--force-download` | Force re-download all files | False |
| `-f` | `--download-folder` | Folder for downloads/extracts | `data/DataDistilleryKG/download` |
| `-i` | `--input-folder` | Input folder for CSV processing | `data/DataDistilleryKG/download` |
| `-o` | `--output` | Output SQLite database file | `data/DataDistilleryKG/ddkg.sqlite` |
| `-O` | `--force-clean-db` | Delete old database and start fresh | False |
| `-X` | `--index` | Create query indexes after loading | False |
| `-I` | `--all-folders` | Process all folders in download directory | False |
| `-l` | `--log` | Log file path (optional) | None |
| `-v` | `--verbose` | Enable debug logging (per-row commits) | False |

### Biomarker Knowledge Graph (biomarker_kg.py)

| Flag | Long | Description | Default |
|------|------|-------------|---------|
| `-i` | `--input-folder` | Input folder with CSV files | *required* |
| `-o` | `--output` | Output SQLite database file | `data/biomarker_kg.sqlite` |
| `-O` | `--force-clean-db` | Delete old database and start fresh | False |
| `-X` | `--index` | Create query indexes after loading | False |
| `-l` | `--log` | Log file path (optional) | None |
| `-v` | `--verbose` | Enable debug logging | False |

## Data Sources

### Data Distillery Knowledge Graph

Downloads are sourced from URLs in `data/DataDistillerySources.tsv`:
- Column 7 contains download URLs
- Files are organized by source (SPARC, etc.)
- Extracted CSVs follow naming pattern: `*.nodes.csv` and `*.edges.csv`

## CSV Format (Data Distillery)

### Node Files (*.nodes.csv)
Supports two header formats:

**Format 1 (Standard)**: `,label,type,identifier_types...`
- **Column 1** (empty header): node_id (UUID)
- **Column 2** (label): Human readable name
- **Column 3** (type): Node classification
- **Columns 4+**: Identifier types (UBERON, FMA, HGNC, etc.) - e.g., "916.0"

Example:
```
,label,type,UBERON,FMA,CARO,CL
c34f2608-e6ce-5541-8b02-3d5f9544ff12,Abdomen,Anatomy,916.0,9577.0,,
```

**Format 2 (Alternative)**: `id,label,identifier_types...`
- **Column 1** (id): node_id (UUID)
- **Column 2** (label): Human readable name
- **Columns 3+**: Identifier types - no type column
- Node type extracted from filename: `<SAB>.<Type>.nodes.csv`

Example (HGNCUNIPROT.Gene.nodes.csv):
```
id,label,HGNC
021bbc1c-db72-5cb2-9662-989adb44b0f9,RBM47,4306
```

**Important**: Nodes without any identifiers are skipped and not stored in the database.

### Edge Files (*.edges.csv)
- **source**: Source node_id (must exist in nodes table)
- **target**: Target node_id (must exist in nodes table)
- **relation**: Edge type (stored as predicate)
- **SAB**: Source authority (extracted from filename if missing)
- **evidence_class**: Evidence type (optional, stored as property)
- **dcc**: Data coordination center (optional, stored as property)

**Important**: Edges are only created if both source and target nodes exist in the database. Edges referencing missing nodes are skipped.

## Database Schema

### nodes table
```sql
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL
);
```

### edges table
```sql
CREATE TABLE edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    sab TEXT,
    FOREIGN KEY (source_node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (target_node_id) REFERENCES nodes(node_id)
);
```

### identifiers table
```sql
CREATE TABLE identifiers (
    identifier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL UNIQUE(node_id, identifier_type, identifier_value),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
);
```

Identifiers are stored in CURIE format: `{identifier_type}:{identifier_value}` (e.g., "UBERON:916")

### properties table (normalized)
```sql
CREATE TABLE properties (
    property_id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_key TEXT NOT NULL,
    property_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    UNIQUE(property_key, property_value, value_type)
);
```

### node_properties and edge_properties tables (many-to-many)
Link nodes/edges to their properties (evidence_class, dcc, etc.)

## Features

- **Automatic delimiter detection**: Handles both tab and comma-separated CSV files
- **Header validation**: Supports two node file header formats (with/without type column)
- **Node filtering**: Only stores nodes with at least one identifier
- **Edge validation**: Only creates edges if both source and target nodes exist in database
- **SAB-aware identifier processing**: Extracts data source (SAB) from filename, applies source-specific processing rules
- **Configurable identifier transformation**: Map (SAB, identifier_type) pairs to processing operations via `dd_config.json`
- **CURIE format identifiers**: External identifiers stored in standard CURIE format with deduplication
- **Normalized properties**: Edge metadata (evidence_class, dcc) deduplicated in properties tables
- **Query indexes**: Separate index file (`kg_indexes.sql`) for optimal query performance after data loading
- **Batch vs. per-row commits**: Normal mode batches commits; verbose mode (`-v`) commits after each node for better debugging
- **Flexible paths**: Separate download folder from processing folder
- **Multi-folder processing**: `-I` flag processes all folders into single database with automatic index creation
- **Logging**: File logging, debug output, progress reporting

## Identifier Configuration (Data Distillery)

The `dd_config.json` file controls special processing of identifier values by data source (SAB) and identifier type in the Data Distillery pipeline:

```json
{
  "xref_processing": [
    {
      "type": "remove_decimal",
      "description": "UBERON and FMA identifiers are integers, remove .0 suffix",
      "sources": {
        "SPARC": ["UBERON", "FMA"],
        "NPO": ["UBERON", "FMA"]
      }
    }
  ],
  "xref_exclude": {
    "NPO": ["SNOMEDCT_US"],
    "SPARC": ["unwanted_column"]
  }
}
```

### Processing Rules

Each rule in `xref_processing` contains:
- **type**: Processing operation (`remove_decimal`, etc.)
- **description**: Human-readable explanation
- **sources**: Map of SAB → list of identifier types to process
  - SAB is extracted from filename (e.g., `SPARC.Anatomy.nodes.csv` → `SPARC`)
  - Identifier types are column headers (e.g., `UBERON`, `FMA`)

### Processing Types

- **`remove_decimal`**: Strips `.0` suffix from numeric values (e.g., `916.0` → `916`)
  - Logs warning if decimal part is non-zero (e.g., `916.5`)
  - Keeps non-numeric values unchanged

### Exclusion Rules

The `xref_exclude` section specifies identifier types to skip per SAB:
- Map of SAB → list of identifier type names to exclude
- Excluded identifiers will not be written to the database
- Useful for skipping low-quality or redundant columns (e.g., SNOMEDCT_US)

### Adding New Rules

1. Edit `dd_config.json`
2. For processing: Add new object to `xref_processing` array with type and SAB mappings
3. For exclusions: Add SAB and list of identifier types to `xref_exclude`
4. Restart the build process

**Example**: Add decimal removal for NPO UBERON and exclude SNOMED:
```json
{
  "xref_processing": [
    {
      "type": "remove_decimal",
      "sources": {"NPO": ["UBERON"]}
    }
  ],
  "xref_exclude": {
    "NPO": ["SNOMEDCT_US"]
  }
}
```

## Examples (Data Distillery)

### Start from scratch (clean build)
```bash
# Download, extract, and create fresh database with indexes
python data_distillery_kg.py -D -O -I -v -l build.log
```
- `-D`: Force download all files
- `-O`: Clean (delete) old database
- `-I`: Process all folders and create indexes
- `-v`: Verbose logging
- `-l build.log`: Log to file

### Incremental builds
```bash
# Download only new files, add to existing database
python data_distillery_kg.py -d

# Reprocess existing files without re-downloading
python data_distillery_kg.py -I
```

### Single folder with indexes
```bash
# Process one folder and create indexes
python data_distillery_kg.py -i data/DataDistilleryKG/download/SPARC -X
```

### Custom paths workflow
```bash
# Download to staging area
python data_distillery_kg.py -D -f data/staging

# Process from validation area
python data_distillery_kg.py -i data/validated -o production.sqlite -X
```

## Troubleshooting (Data Distillery)

### "No nodes loaded" or "Loaded 0 nodes"
- Nodes without any identifiers are skipped - verify identifier columns have values
- Check that node file has correct header format (Format 1 or Format 2)
- Use `-v` flag to see debug details about which rows are skipped
- Check `dd_config.json` for exclusion rules that might be removing all identifiers

### "Skipped edges with missing nodes"
- Edges require both source and target nodes to exist in database
- If many edges are skipped, check that node files are processed before edge files
- Use `-v` flag to see which edges are missing nodes
- Verify node_id format matches between node and edge files

### "No CSV files found" warning
- Verify download folder has subdirectories with `*.nodes.csv` and `*.edges.csv` files
- Check that files were extracted correctly with `-v` flag
- Use `-D` to force re-download and extract

### Decimal values being stored (916.0 vs 916)
- SPARC and other data sources with UBERON/FMA are configured to remove `.0` suffix via `dd_config.json`
- Other data sources or identifier types store values exactly as they appear in CSVs
- To add processing for other data sources, edit `dd_config.json` and add a rule mapping (SAB, identifier_type) → processing type
- Non-zero decimals (e.g., `916.5`) generate warnings but are kept as-is

### Query performance issues
- Use `-X` or `-I` flags to create query indexes after loading
- Indexes are stored in `kg_indexes.sql` and created after all data loads
- Indexes significantly improve query performance on large datasets
