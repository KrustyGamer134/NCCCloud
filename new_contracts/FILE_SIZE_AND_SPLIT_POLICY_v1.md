# File Size And Split Policy v1

Status: AUTHORITATIVE

Purpose: Keeps docs and contract files readable for humans and coding agents.

## 1) General Rule

Prefer small focused files over large mixed-purpose files.

## 2) Split Rule

Split a file when it starts to cover more than one of these at the same time:

- ownership rules
- payload/schema definitions
- workflow sequencing
- per-game specifics
- operational instructions

## 3) Practical Size Rule

Preferred target:

- short rule files: under 100 lines
- normal contract files: under 200 lines

Warning threshold:

- around 250 to 300 lines, split unless there is a strong reason not to

## 4) Structure Rule

- use one concern per file
- use section contracts for ownership
- use child contracts for schemas and workflows
- do not create giant master files that try to hold the whole system

## 5) Agent Rule

If a file is getting long, do not keep appending to it by default.

First ask:

- should this be a child contract?
- should this be a shared schema file?
- should this be a game-specific profile file?
