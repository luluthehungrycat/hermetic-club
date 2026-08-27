## Purpose

Defines safe, reviewable boundaries for sharing version-controlled skills, memories, projects, and handoff artifacts between agents through linked repositories.

## ADDED Requirements

### Requirement: Artifact synchronization is explicit and curated
The system SHALL expose only explicitly selected skills, memories, projects, policies, and handoff artifacts for export or import, and SHALL NOT synchronize complete Hermes or Hermetic Club home directories by default.

#### Scenario: Export selected project
- **WHEN** an authorized user or agent exports a selected project
- **THEN** the export contains the declared project files and metadata only

#### Scenario: Whole home directory request
- **WHEN** a client requests synchronization of an entire agent home directory
- **THEN** the system rejects the request or requires an explicit privileged override outside the normal workflow

### Requirement: Imports are reviewable before activation
The system SHALL provide a diff or manifest preview for imported artifacts and SHALL require explicit authorization before activating imported skills, memories, or policies.

#### Scenario: Import contains changes
- **WHEN** a user previews an artifact import
- **THEN** the system identifies added, changed, and removed files before activation

#### Scenario: Import is not approved
- **WHEN** a previewed import is not approved
- **THEN** the artifacts remain inactive and do not alter the active agent environment

### Requirement: Artifact provenance is recorded
The system SHALL record the source repository, commit or revision, exporting identity, importing identity, and approval event for every activated artifact set.

#### Scenario: Approved import provenance
- **WHEN** an artifact set is activated after approval
- **THEN** the system exposes provenance sufficient to identify the exact source revision and approving identity

### Requirement: Handoffs support Git-backed work
The system SHALL support handoffs that identify a project, repository, branch, revision, notes, and intended recipient while preserving non-Git handoffs.

#### Scenario: Git-backed handoff
- **WHEN** an agent publishes a handoff with a repository and branch
- **THEN** the recipient can retrieve the handoff context and clone or fetch the referenced branch using its own authorized Git credentials

#### Scenario: Notes-only handoff
- **WHEN** an agent publishes a handoff without a repository
- **THEN** the handoff remains valid as a notes-only transfer and does not require Forgejo
