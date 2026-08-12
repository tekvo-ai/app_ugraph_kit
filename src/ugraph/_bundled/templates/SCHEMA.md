---
type: overview
title: "Knowledge Base Schema (OKF-v)"
description: "Page types, frontmatter contracts, relationships, and linking rules for this knowledge base."
---

# Knowledge Base Schema — OKF-v

This knowledge base uses plain Markdown, YAML frontmatter, generated indexes,
and relative links. Raw source material remains inspectable; derived pages link
back to the sources that support them.

## Directory layout

```text
knowledge/
├── index.md
├── SCHEMA.md
├── taxonomy.json
├── concepts/
├── entities/
│   ├── tools/
│   ├── people/
│   └── organizations/
├── sources/
├── raw/
└── _mocs/
```

`concepts/` is flat. Subject grouping is represented by the `domain` field,
which keeps file paths stable when classification changes.

## Page contracts

All dates use `YYYY-MM-DD`.

### Concept

Location: `concepts/<slug>.md`

```yaml
---
type: concept
title: "Generation-verification loop"
description: "A generator proposes outputs and an independent gate rejects unsupported ones."
domain: agentic_systems
status: growing
tags: [verification]
sources: [example/source-slug]
created: 2026-01-01
updated: 2026-01-01
---
```

Required fields: `type`, `title`, `description`, `domain`, `status`, `created`,
and `updated`. Status is one of `seed`, `growing`, or `evergreen`.

### Entity

Location: `entities/{tools,people,organizations}/<slug>.md`

```yaml
---
type: entity
subtype: person
title: "Example Person"
description: "A short, factual description."
resource: https://example.com
handles: ["@example"]
created: 2026-01-01
updated: 2026-01-01
---
```

Required fields: `type`, `subtype`, `title`, `description`, `created`, and
`updated`. Subtype is one of `tool`, `person`, or `organization`.

### Source

Location: `sources/<publisher>/<slug>.md`

```yaml
---
type: source
source_type: article
title: "Example source"
description: "The source's central claim in one sentence."
slug: example/source
url: https://example.com/source
created: 2026-01-01
updated: 2026-01-01
---
```

Required fields: `type`, `source_type`, `title`, `description`, `slug`,
`created`, and `updated`. Video sources additionally require `youtube_id`,
`url`, `published`, `duration`, and `raw`.

### Raw transcript

Location: `raw/<publisher>/<slug>.md`

```yaml
---
type: raw-transcript
immutable: true
slug: example/source
url: https://example.com/source
---
```

Never edit generated raw transcripts by hand. Timestamped transcript blocks use:

```text
[00:04:12] The exact source text appears here.
```

### MOC and overview

Maps of content use `type: moc`. Entry points, redirects, and this schema use
`type: overview`. Both require `type` and `title`.

## Relationships

A Markdown link under one of these headings asserts an edge:

- `## Prerequisites`
- `## Builds on`
- `## Contrasts with`
- `## Implemented by`
- `## Related`
- `## Sources`

Typed edges should be linked in both directions where that relationship is
meaningful. Provenance links from concepts to sources do not require a forward
link from every source.

## Linking rules

- Use relative Markdown links inside the knowledge base.
- Do not use `[[wikilinks]]` in the strict tree (`concepts`, `entities`,
  `sources`, and `_mocs`).
- Every link must resolve.
- Filenames are stable identities; use kebab-case and do not rename casually.
- Prefer one topic per page.

## Citation rule

Claims from timestamped material cite the source and exact time:

```markdown
The speaker describes a verification loop
([Example talk](../sources/example/talk.md) @ 00:14:32).
```

Text extraction candidates carry a content-addressed chunk anchor. ugraph's
verification gate rejects quotes that do not occur verbatim in the source.

## Domains

The closed vocabulary is defined in `taxonomy.json`. The default domains are:

`agentic_systems`, `ai_engineering`, `rag`, `local_llms`,
`machine_learning`, `mathematics`, `system_design`, and `product`.

## Validation

Run:

```bash
ugraph lint
ugraph verify
```

Errors include malformed frontmatter, unknown closed-vocabulary values, broken
links, invalid strict-tree wikilinks, and source pages whose raw target is
missing. Warnings identify issues such as orphan pages and one-way typed edges.
