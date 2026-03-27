# CODERABBIT.md

## Review Focus

Prioritize:

* correctness
* architectural boundary violations
* contract violations
* runtime bugs
* edge cases

Deprioritize:

* style suggestions
* formatting changes
* subjective refactors

---

## Architecture Constraints

System flow:

Web UI ? Backend ? Agent ? Runtime/Core ? Game

Strict rules:

* UI must not access filesystem or plugin files
* Backend must not execute local processes
* Agent is the only layer that touches the machine
* Core must remain deterministic and game-agnostic

Flag ANY violation of these rules as high priority.

---

## Plugin Rules

* Plugins are data-driven (`plugin.json`)
* Core must not contain game-specific logic

Flag:

* hardcoded ARK logic in core
* game-specific paths in generic code

---

## Review Style

* Be concise
* Focus on real issues
* Avoid long explanations
* Avoid suggesting multiple alternatives

---

## Ignore

Do not flag:

* minor formatting issues
* naming preferences
* large refactors unless required for correctness

---

## Priority Levels

High:

* bugs
* broken logic
* architecture violations
* contract violations

Medium:

* risky patterns
* missing validation
* potential edge cases

Low:

* style
* readability suggestions
