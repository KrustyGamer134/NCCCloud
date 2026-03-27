# Legacy Archive Plan v1

Status: AUTHORITATIVE

Purpose: Defines what was quarantined out of the active cloud-target repo surface and why.

## 1) Active Areas Kept In Place

- `ncc-frontend/`
- `ncc-backend/`
- `ncc-agent/`
- `core/`
- `plugins/`
- `new_contracts/`
- active tests not tied specifically to desktop GUI or legacy CLI

## 2) Legacy Areas To Archive

- desktop GUI code
- old contract set
- desktop CLI entrypoint and CLI-only docs/tests
- historical planning/docs that reinforce the old architecture
- desktop packaging files

## 3) Quarantine Rule

Archive, do not delete.

Anything moved out of the active repo surface should remain recoverable under a dedicated legacy folder until the cloud architecture is proven.
