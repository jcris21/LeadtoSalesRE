## ADDED Requirements

### Requirement: Grounded retrieval over an approved, organization-scoped knowledge base
The system SHALL provide `KnowledgeService.answer(organization_id, query, category=None, top_k=3)`
that embeds `query`, retrieves at most `top_k` `knowledge_documents` rows filtered by
`organization_id` and `approved = true` (and by `category` when provided), and returns a
`KnowledgeAnswer` whose `answer_text` is composed only from the retrieved passages' content.

#### Scenario: Lead asks about a zone's plusvalia
- **WHEN** `KnowledgeService.answer` is called with a query about a zone's price appreciation and
  an approved, matching `plusvalia` document exists for that organization
- **THEN** the returned `KnowledgeAnswer.answer_text` contains only text drawn from that document's
  `content`, and `source_document_ids` references it

### Requirement: Tenant and approval isolation
The system SHALL never retrieve a `knowledge_documents` row belonging to a different
`organization_id`, and SHALL never retrieve a row with `approved = false`, regardless of embedding
similarity.

#### Scenario: Cross-tenant document is never retrieved
- **WHEN** organization A's knowledge base has no matching approved document, but organization B
  has a highly similar approved document
- **THEN** `KnowledgeService.answer` called with organization A's id returns `found=False` and
  never references organization B's document

#### Scenario: Unapproved document is never retrieved
- **WHEN** the only matching document for a query has `approved = false`
- **THEN** `KnowledgeService.answer` returns `found=False`

### Requirement: Extractive, grounded answer assembly
The system SHALL assemble `KnowledgeAnswer.answer_text` only by concatenating/trimming retrieved
passage content, without invoking a free-form text generator, so the answer can never contain a
figure or fact absent from the retrieved, approved passages.

#### Scenario: No unverified figures in the answer
- **WHEN** `KnowledgeService.answer` retrieves one or more passages
- **THEN** every substring of `answer_text` is drawn from the retrieved passages' `content`

### Requirement: Graceful empty-knowledge-base handling
The system SHALL return a clear `found=False` result with no exception when no approved document
matches the organization/category/query, including when the knowledge base has zero documents.

#### Scenario: Empty knowledge base
- **WHEN** `KnowledgeService.answer` is called for an organization with zero `knowledge_documents`
  rows
- **THEN** the call returns a `KnowledgeAnswer` with `found=False` and does not raise
