"""Shared library for the Coscientist skills.

Import submodules directly (e.g. `from lib.cache import paper_dir`) rather
than relying on this package's top-level namespace. Submodules have
different dependencies — keeping the top-level bare means a script that
only needs `lib.cache` doesn't pull in `slugify`/etc. transitively.
"""
