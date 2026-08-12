# Phase A candidate extraction — text documents (chunk-anchored)

You are extracting candidate concepts from one pasted text document. The document is
given to you as numbered chunks (`--- CHUNK <id> ---`). This is mechanical work:
find the claims, copy the words exactly. Do not synthesize, do not editorialize, do
not merge ideas across the document.

## Rules

1. `verbatim_quote` MUST be an exact substring of ONE chunk, copied
   character-for-character (whitespace may differ). Never quote across a chunk
   boundary. If you cannot quote it, it is not a concept — it is your paraphrase,
   and it will be rejected by a substring test before anything is written.
2. Do NOT invent anchors or timestamps. The pipeline derives the anchor (chunk id)
   from your quote. You only supply name, claim, and quote.
3. `claim` is one sentence: what the text asserts, in your words. The claim may
   paraphrase; the quote may not.
4. `name` is a short concept name (e.g. "reciprocal rank fusion").
5. Prefer 3–8 strong concepts over 20 weak ones. Marketing copy, a changelog of
   trivia, or content-free notes are `yield: "none"` with an empty list — that is a
   correct answer.
6. Tables count as text: quoting one full row is fine if it sits inside one chunk.

## Output

Return ONLY this JSON object, no prose, no code fence:

```json
{
  "yield": "high | medium | low | none",
  "concepts": [
    {
      "name": "concept name",
      "claim": "one sentence: what is asserted",
      "verbatim_quote": "exact substring from one chunk"
    }
  ]
}
```
