# Change Control And Versioning Policy v1

Status: AUTHORITATIVE

Purpose: Defines how the new contract set changes over time.

## 1) Versioning Rules

### 1.1 Major version bump

Required for:

- removed or renamed fields
- changed ownership boundaries
- changed lifecycle semantics
- changed state meanings
- changed required flow ordering

### 1.2 Minor version bump

Allowed for:

- additive optional fields
- additive non-breaking sections
- clarifying rules that do not change semantics

### 1.3 Patch version

Allowed for:

- typo fixes
- formatting fixes
- wording clarifications with no semantic effect

## 2) Required Update Pattern

For any architecture change:

1. Update the owning section contract.
2. Update affected dependent section contracts.
3. Update affected shared schema contracts.
4. Update tests or schema enforcement in the same change group.

## 3) Cross-Section Rule

If a change crosses section boundaries, no single contract may be updated in isolation when that would leave the overall contract set contradictory.

## 4) Legacy Reference Rule

- Historical contracts may be consulted for context.
- Historical contracts must not override `new_contracts/`.

## 5) Status Labels

Allowed labels:

- `AUTHORITATIVE`
- `DRAFT`
- `HISTORICAL`

All files in this contract set should converge toward `AUTHORITATIVE`.
