# CFDE REVEAL Knowledge Graph

The CFDE REVEAL Knowledge Graph is a statistically inferred genomic evidence graph to integrate and disseminate knowledge within the Common Fund Data Ecosystem (CFDE).

https://cfdeknowledge.org/

The CFDE REVEAL Knowledge Graph connects biological processes and genes to human disease endpoints using the Common Fund Data Ecosystem (CFDE), a collection of high-profile data generation programs funded by the NIH Common Fund. CFDE datasets are represented as gene sets that are then linked to human traits by applying two Bayesian methods: 
1) PIGEAN (Priors Inferred from GEne ANnotations) to identify probabilistic relationships between these gene sets and human traits by jointly inferring which genes are trait-relevant and which gene sets predict trait-relevance. Visit our webinar to learn more about PIGEAN: https://www.youtube.com/watch?v=b1fmzhgE3lI
2) EAGGL (Enrichment Analysis, Gene Grouping, and LLMs) to learn latent factors that model disease mechanisms. The base knowledge graph includes edges among genes, gene sets, phenotypes, and disease mechanisms, each annotated with a probability of association or weight. Visit our webinar to learn more about EAGGL: https://www.youtube.com/watch?v=-cF4BFYlyUQ

## File Schema

The full graph is accessible from: https://dig-knowledge-graph.s3.us-east-1.amazonaws.com/raw/cfde_kg_v1.csv.gz

The graph is stored as an edge list CSV (total edges: **30,002,794**) with one row per edge.

| Column | Description |
| :--- | :--- |
| `Source` | Source node label. |
| `Source_Type` | Source node type. |
| `Target` | Target node label. |
| `Target_Type` | Target node type. |
| `Edge_Type` | Relationship type. |
| `Weight` | Edge score. Interpretation depends on `Edge_Type`; not all weights are probabilities. |

### Node Types

The graph uses the following node types:

| Node Type | Description |
| :--- | :--- |
| `Gene` | Gene labels represented in the source data. |
| `Gene_Set` | CFDE Gene sets, pathways, signatures, or other grouped gene annotations. |
| `Trait` | Human traits, phenotypes, diseases, or endpoints sourced from rare diseases in the Orphanet database, common traits in the NHGRI Association to Function Knowledge Portal, and the NHGRI GWAS Catalog. |
| `Factor` | Latent factor or mechanism labels generated from EAGGL. In this export, factor labels are contextualized by trait, for example `... (trait context: ...)`. |

Note: Each factor is uniquely labeled for each trait, so there generally isn't overlap.

### Node Numbers

Genes: 56,375
Gene sets: 224,648
Traits: 6,049
Factors / mechanisms: 44,680

### Edge Types

| Edge Type | Connects | Weight | Inclusion Rule |
| :--- | :--- | :--- | :--- |
| `Gene_in_GeneSet` | `Gene` -> `Gene_Set` | Binary gene-set membership. | Unique gene/gene-set membership pairs represented in the source data. |
| `Gene_to_Trait` | `Gene` -> `Trait` | PIGEAN combined gene-trait relevance score: direct genetic evidence plus annotation-informed indirect support. Higher means stronger evidence. | `combined > 1.0` |
| `GeneSet_to_Trait` | `Gene_Set` -> `Trait` | PIGEAN uncorrected gene-set effect score. Higher positive values mean the gene set is more strongly associated with trait-relevant genes. | `beta_uncorrected > 0.1` |
| `Trait_to_Factor` | `Trait` -> `Factor` | EAGGL factor relevance score for the trait. | `Weight > 0.1` |
| `Gene_to_Factor` | `Gene` -> `Factor` | EAGGL gene loading on the factor. Higher means the gene contributes more strongly to that mechanism. | `Weight > 0.1` |
| `GeneSet_to_Factor` | `Gene_Set` -> `Factor` | EAGGL gene-set/annotation loading on the factor. Higher means the gene set better represents that mechanism. | `Weight > 0.1` |

Weights are comparable within an edge type but should not be compared directly across all edge types.

## Edge Numbers

Gene -> Gene set: 11,921,972
Gene set -> Factor: 9,092,039
Gene -> Factor: 6,701,352
Gene -> Trait: 1,299,086
Gene set -> Trait: 948,427
Trait -> Factor: 39,918

## Traits by source 

NHGRI GWAS Catalog: 2,530
Orphanet rare disease database: 2,313
NHGRI Association to Function Knowledge Portal: 1,236 

## Gene sets by source 

LINCS chemical perturbations: 38,040
LINCS knockouts: 35,911
MSigDB: 27,092
IDG coexpression: 13,427
MoTrPAC: 12,723
GTEx aging: 11,995
GlyGen: 11,892
GTEx tissues: 10,155
Mouse gene annotations (2024): 7,459
KOMP: 7,459
Knowledge Center differential expression: 3,997
IDG targets: 2,003

## Example Queries

The graph supports evidence-path queries. The examples below are conceptual traversals; depending on the graph query system, some paths may require traversing edges in reverse direction.

* `Gene -> Factor <- Trait`: find latent mechanisms that connect a gene to disease or phenotype endpoints.
* `Gene -> Gene_Set -> Trait`: find gene set evidence connecting a gene to a trait.
* `Trait -> Factor <- Gene` or `Trait -> Factor <- Gene_Set`: explore factors associated with a trait and the genes or gene sets linked to those factors.

## Contact

* **Jason Flannick** - flannick@broadinstitute.org
* **Noël Burtt** - burtt@broadinstitute.org
