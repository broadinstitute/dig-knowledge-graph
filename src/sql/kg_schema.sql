-- Knowledge Graph Schema for SQLite
-- Fully normalized with unique property key-value pairs

-- Core entities
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    label TEXT NOT NULL
);

CREATE TABLE edges (
    edge_id TEXT PRIMARY KEY,
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
    edge_id TEXT NOT NULL,
    property_id INTEGER NOT NULL,
    PRIMARY KEY (edge_id, property_id),
    FOREIGN KEY (edge_id) REFERENCES edges(edge_id) ON DELETE CASCADE,
    FOREIGN KEY (property_id) REFERENCES properties(property_id) ON DELETE CASCADE
);

-- External identifiers
CREATE TABLE identifiers (
    identifier_id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id) ON DELETE CASCADE
);


-- ============================================================================
-- INDEX STRATEGY
-- ============================================================================

-- Loading Indexes (required during bulk insert)
CREATE INDEX idx_properties_key_value ON properties(property_key, property_value);

-- Query Indexes (create after population)
CREATE INDEX idx_edges_source ON edges(source_node_id);
CREATE INDEX idx_edges_target ON edges(target_node_id);

CREATE INDEX idx_node_properties_property ON node_properties(property_id);
CREATE INDEX idx_edge_properties_property ON edge_properties(property_id);

CREATE INDEX idx_identifiers_type_value ON identifiers(identifier_type, identifier_value);

CREATE INDEX idx_nodes_type ON nodes(type);
CREATE INDEX idx_edges_predicate ON edges(predicate);
