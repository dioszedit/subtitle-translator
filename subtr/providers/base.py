"""Közös séma-segédek a provider-adaptereknek."""


def no_additional(node):
    """JSON-séma másolata az `additionalProperties` kulcsok nélkül.

    A Gemini response_schema nem ismeri az additionalProperties-t, a Codex
    strict módja viszont megköveteli — ezért ugyanabból a sémából két
    változat kell. A hívó a Codex-alakot írja meg, a Gemini-adapter ezzel
    származtatja a magáét."""
    if isinstance(node, dict):
        return {k: no_additional(v) for k, v in node.items()
                if k != "additionalProperties"}
    if isinstance(node, list):
        return [no_additional(v) for v in node]
    return node
