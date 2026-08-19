"""
ugraph-kit — build an agent-navigable knowledge base from any input you trust.

Clipboard, paste, pipe, file, or URL. Plain markdown, YAML frontmatter, relative links.
No database, no embeddings. An agent reads an index, follows links to the few pages it
needs, and cites a chunk or timestamp in an immutable raw source.

The format is the Open Knowledge Format, originated by Cole Medin
(github.com/coleam00/cole-medin-knowledge-base). This package is an independent
implementation of it as a reusable tool; divergences are marked OKF-v in SCHEMA.md.

Library entry points:

    from ugraph import config, indexes, ingest, lint, status, verify
    from ugraph.sources import youtube

    cfg = config.load(kb="~/vault/knowledge")
    ingest.capture_text(cfg, "a claim you care about")   # any text
    ingest.ingest_path(cfg, "./note.md")                 # any file
    youtube.ingest(cfg, "https://youtube.com/@example", limit=25)
    indexes.write_all(cfg)
    findings, pages = lint.lint(cfg)
    issues = verify.verify(cfg)
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
