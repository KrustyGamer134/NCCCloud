"""Test package marker.

Some tests import helper modules via the dotted path `tests.<module>`.
Pytest does not automatically treat the `tests/` directory as an importable
package unless it contains an `__init__.py`.
"""