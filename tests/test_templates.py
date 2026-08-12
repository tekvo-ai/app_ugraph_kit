import json

from ugraph import templates


def test_scaffold_templates_are_bundled():
    schema = templates.read("SCHEMA.md")
    taxonomy = json.loads(templates.read("taxonomy.json"))

    assert "Knowledge Base Schema" in schema
    assert "ai_engineering" in taxonomy["domains"]
    assert taxonomy["entity_dirs"]["person"] == "people"
