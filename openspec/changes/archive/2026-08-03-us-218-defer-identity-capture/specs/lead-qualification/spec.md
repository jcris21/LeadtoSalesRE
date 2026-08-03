## ADDED Requirements

### Requirement: Turn-1 identity ask excludes DNI
While a conversation has no linked Lead, the Coordinator's identity gate
SHALL ask only for the contact's full name to create the wacrm deal. It
SHALL NOT request or mention DNI on this turn. DNI provided voluntarily in
the same message (alongside the name) SHALL still be captured and sent to
wacrm.

#### Scenario: First turn without a name
- **WHEN** a message arrives on a conversation with no linked Lead and the
  message does not carry a recognizable name
- **THEN** the reply asks only for the contact's full name
- **AND** the reply makes no mention of DNI

#### Scenario: First turn with name and DNI both volunteered
- **WHEN** the first message carries both a name and an 8-digit DNI
- **THEN** the Lead is created in wacrm with both `contact_name` and
  `contact_dni` populated

### Requirement: Deferred DNI request after a value moment
Once a conversation reaches the `RECOMMENDATION` state (a recommendation or
equivalent value moment has already been delivered) and the linked Lead has
not volunteered a DNI, the Coordinator SHALL append a DNI request to that
turn's reply. This request SHALL be additive — it SHALL NOT replace or
block the qualification, scheduling, or knowledge-answer content already
computed for that turn.

#### Scenario: DNI requested after recommendation shown
- **WHEN** a message arrives on a conversation whose state is
  `RECOMMENDATION`, the Lead is linked, and no DNI has been volunteered yet
- **THEN** the reply contains the turn's normal response
- **AND** the reply also contains a request for the contact's DNI

#### Scenario: DNI request never appears before RECOMMENDATION
- **WHEN** a message arrives on a conversation whose state is `Qualification`
  (or any state before `RECOMMENDATION`)
- **THEN** the reply contains no DNI request

#### Scenario: Volunteering the DNI during RECOMMENDATION stops it being fed to qualification
- **WHEN** a message during `RECOMMENDATION` consists solely of an 8-digit
  DNI
- **THEN** the DNI is recorded on the turn's decision trace
- **AND** the message is excluded from qualification extraction that turn
