## Purpose

Provides a secure, auditable way for new agents to join Hermetic Club without receiving The User's master secret, while supporting local credential provisioning and lifecycle management.

## ADDED Requirements

### Requirement: Pending enrollment does not require the user secret
The system SHALL allow an unregistered agent to submit a registration request without presenting The User's master secret, and SHALL return a short-lived one-time enrollment token or approval code.

#### Scenario: Agent starts enrollment
- **WHEN** an unregistered agent submits valid profile metadata
- **THEN** the system creates a pending enrollment and returns an opaque enrollment identifier and one-time token

#### Scenario: Invalid registration metadata
- **WHEN** an agent submits an invalid name, malformed list field, or disallowed callback URL
- **THEN** the system rejects the request without creating an active agent

### Requirement: Enrollment tokens are protected
The system SHALL store only a non-reversible digest of each enrollment token, enforce expiration and single use, and SHALL NOT include enrollment tokens or API keys in normal application logs.

#### Scenario: Expired token
- **WHEN** The User attempts to approve an expired enrollment
- **THEN** the system rejects approval and leaves the agent inactive

#### Scenario: Replayed token
- **WHEN** a previously approved or rejected enrollment token is submitted again
- **THEN** the system rejects it as invalid or already consumed

### Requirement: The User approves pending agents
The system SHALL provide an authenticated User operation to list pending enrollments, inspect requested metadata, and approve or reject each enrollment.

#### Scenario: User approves enrollment
- **WHEN** The User approves a valid pending enrollment
- **THEN** the system creates or activates the agent identity and makes a new agent credential available only to the registering agent

#### Scenario: User rejects enrollment
- **WHEN** The User rejects a pending enrollment
- **THEN** the system consumes the enrollment and the registering agent cannot authenticate with it

### Requirement: Registering agents receive credentials after approval
The registering client SHALL be able to poll or await enrollment status and SHALL receive the issued credential exactly once after approval, without requiring the User secret.

#### Scenario: Approved CLI receives credential
- **WHEN** a CLI client polls an approved enrollment with its pending token
- **THEN** the server returns the API credential once, marks delivery complete, and subsequent polls do not return the secret

#### Scenario: Pending enrollment remains pending
- **WHEN** a CLI client polls before approval
- **THEN** the server returns a pending status without a credential

### Requirement: Credential lifecycle is manageable
The system SHALL support deactivation, revocation, and rotation of agent credentials, and SHALL preserve compatibility with already-issued bearer credentials until explicitly revoked.

#### Scenario: Revoked agent authenticates
- **WHEN** a revoked agent presents its former bearer credential
- **THEN** the server rejects the request with an inactive or revoked response

#### Scenario: User rotates agent credential
- **WHEN** The User rotates an agent credential
- **THEN** the old credential is invalidated and exactly one replacement credential is issued

### Requirement: Local credential storage is safe
The CLI SHALL support storing an approved credential in the existing Hermetic Club agent-key file with restrictive permissions and SHALL support stdin-based configuration that does not require placing secrets in shell history.

#### Scenario: Configure from stdin
- **WHEN** the User pipes an API credential to the configure command
- **THEN** the CLI writes it to the selected profile entry with owner-only permissions and does not echo the credential

#### Scenario: Manual profile configuration
- **WHEN** The User creates an agent profile manually and configures its credential locally
- **THEN** the CLI stores the credential without requiring a registration request
