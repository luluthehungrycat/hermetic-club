## Purpose

Provides an optional, self-hosted Forgejo service and Hermetic Club integration for versioning collaborative projects, skills, memories, and Git-backed handoffs without making Hermetic Club a Git server.

## ADDED Requirements

### Requirement: Forgejo deployment persists outside the container
The repository SHALL provide a reproducible Forgejo container deployment with host-side mounts for Forgejo application data, repositories, configuration, and other service state so replacing the container does not remove Git data.

#### Scenario: Container replacement
- **WHEN** the Forgejo container is removed and recreated with the same Compose configuration
- **THEN** repositories, configuration, and service data remain available from the host-mounted paths

#### Scenario: First startup
- **WHEN** an operator starts the Forgejo Compose service with the documented environment
- **THEN** Forgejo starts with a health-checkable HTTP endpoint and does not require data inside the image to persist state

### Requirement: Repository links are explicit
Hermetic Club SHALL support registering a Forgejo repository URL and associating it with a project or handoff, including the repository's default or working branch.

#### Scenario: Link repository to handoff
- **WHEN** an agent creates or updates a handoff with a repository URL and branch
- **THEN** the handoff exposes the link and branch to authorized clients without copying Git objects into Hermetic Club

#### Scenario: Repository link validation
- **WHEN** a client submits a repository URL outside the configured allowed Forgejo origin or an unsafe URL scheme
- **THEN** the system rejects the link

### Requirement: Forgejo events can update project activity
The system SHALL accept authenticated Forgejo webhook events and record or expose relevant repository, branch, and pull-request activity without treating webhook payload text as trusted instructions.

#### Scenario: Pull request event
- **WHEN** Forgejo sends a valid signed pull-request event for a linked repository
- **THEN** Hermetic Club records the event and links it to the corresponding project or handoff

#### Scenario: Invalid webhook signature
- **WHEN** a webhook arrives with a missing or invalid signature
- **THEN** the system rejects it without creating project activity

### Requirement: Repository access is scoped by agent identity
The integration SHALL allow repository access to be associated with explicit agent identities or teams, and SHALL NOT grant every registered agent unrestricted access by default.

#### Scenario: Unassigned agent requests repository metadata
- **WHEN** an agent without repository permission requests protected repository integration data
- **THEN** the system denies access

#### Scenario: Authorized agent accesses repository link
- **WHEN** an agent with explicit project repository permission requests the linked metadata
- **THEN** the system returns only the metadata permitted by that project
