-- Knowledge Graph Schema for SQLite
-- Fully normalized with unique property key-value pairs

-- Core entities
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    sab TEXT,
    FOREIGN KEY (source_node_id) REFERENCES nodes(node_id),
    FOREIGN KEY (target_node_id) REFERENCES nodes(node_id)
);

-- Normalized properties: unique key-value pairs stored once
CREATE TABLE properties (
    property_id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_key TEXT NOT NULL,
    property_value TEXT NOT NULL,
    value_type TEXT NOT NULL,  -- 'string', 'integer', 'float', 'boolean', 'date', 'json'
    UNIQUE(property_key, property_value, value_type)
);

-- Map nodes to properties (many-to-many)
CREATE TABLE node_properties (
    node_id TEXT NOT NULL,
    property_id INTEGER NOT NULL,
    PRIMARY KEY (node_id, property_id),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE,
    FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
);

-- Map edges to properties (many-to-many)
CREATE TABLE edge_properties (
    edge_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    PRIMARY KEY (edge_id, property_id),
    FOREIGN KEY (edge_id) REFERENCES edges(edge_id) ON DELETE CASCADE,
    FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
);

-- External identifiers
CREATE TABLE identifiers (
    identifier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    UNIQUE(node_id, identifier_type, identifier_value),
    FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
);


-- ============================================================================
-- INDEX STRATEGY
-- ============================================================================

-- Loading Index (required during bulk insert for deduplication)
CREATE INDEX idx_properties_key_value ON properties(property_key, property_value);

-- Merge Index (for database merge operations: find properties by value)
CREATE INDEX idx_properties_value ON properties(property_value);

-- Merge Index (for database merge operations: find identifiers by value)
CREATE INDEX idx_identifiers_value ON identifiers(identifier_value);


