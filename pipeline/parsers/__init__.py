"""Parsers. Each tournament YAML names its parser as ``module:function`` (module relative to
this package), e.g. ``parser: rr_matrix:parse``. Signature::

    def parse(t: pipeline.registry.Tournament, w: pipeline.schema.TournamentWriter, **options) -> None

``options`` are the tournament's ``parser_options``. Raise on unrecoverable problems; record
recoverable oddities with ``w.warn(...)``.
"""
