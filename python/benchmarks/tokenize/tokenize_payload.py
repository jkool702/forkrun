"""LLM tokenization payload — same logic in Python and C (W-PY25).

Simplified BPE-like algorithm:
1. Split text on whitespace
2. Per word: vocabulary hit -> token ID; else strip one known
   suffix (first match in SUFFIXES order, len(word) > len+suffix+2)
   and emit stem + suffix IDs when the stem hits; else UNK (0)
3. Document stats (count, unique, diversity)
4. Quality filter: 20 <= n_tokens <= 1000, diversity >= 0.1
5. Output: JSON {doc_id, tokens, n_tokens, n_unique, diversity}

The C plugin (plugins/tokenize_plugin.c) implements this EXACT
algorithm, including suffix order and quality constants. Validation
compares parsed outputs for equality.
"""

import json

# Suffix list AND ORDER are load-bearing (first match wins) — the C
# plugin carries the identical table in the identical order.
SUFFIXES = ["ing", "tion", "ness", "ment", "able", "ible", "ful",
            "less", "ly", "er", "est", "ed", "es", "s"]

MIN_TOKENS = 20
MAX_TOKENS = 1000
MIN_DIVERSITY = 0.1


class Tokenizer:
    def __init__(self, vocab_path=None, vocab=None):
        if vocab is not None:
            self.vocab = dict(vocab)
        else:
            self.vocab = {}
            with open(vocab_path) as fh:
                for line in fh:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) == 2:
                        self.vocab[parts[1]] = int(parts[0])

    def tokenize(self, text):
        """Text -> list of token IDs (UNK=0 for misses)."""
        tokens = []
        vocab = self.vocab
        for word in text.split():
            hit = vocab.get(word)
            if hit is not None:
                tokens.append(hit)
                continue
            found = False
            for suffix in SUFFIXES:
                if word.endswith(suffix) and \
                        len(word) > len(suffix) + 2:
                    stem = word[:-len(suffix)]
                    stem_id = vocab.get(stem)
                    if stem_id is not None:
                        tokens.append(stem_id)
                        tokens.append(vocab.get(suffix, 0))
                        found = True
                        break
            if not found:
                tokens.append(0)
        return tokens

    def process_document(self, doc_bytes):
        """One JSONL line -> output dict, or None (skip)."""
        try:
            doc = json.loads(doc_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(doc, dict):
            return None
        text = doc.get("text", "")
        if not isinstance(text, str):
            return None
        tokens = self.tokenize(text)
        n_tokens = len(tokens)
        n_unique = len(set(tokens))
        diversity = n_unique / n_tokens if n_tokens > 0 else 0.0
        if n_tokens < MIN_TOKENS or n_tokens > MAX_TOKENS:
            return None
        if diversity < MIN_DIVERSITY:
            return None
        return {
            "doc_id": doc.get("doc_id"),
            "tokens": tokens,
            "n_tokens": n_tokens,
            "n_unique": n_unique,
            "diversity": round(diversity, 4),
        }


_tokenizer = None


def get_tokenizer(vocab_path):
    """Process-wide tokenizer (loaded once; fork-inherited by workers)."""
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = Tokenizer(vocab_path=vocab_path)
    return _tokenizer


def reset_tokenizer():
    """Forget the cached tokenizer (tests only)."""
    global _tokenizer
    _tokenizer = None


def batch_payload(lines, tokenizer):
    """Shared batch loop (forkrun/Pool/Executor/Ray/HF adapters).

    Exact-count convention (same as the ML payloads): one output
    segment per non-blank input line (b"" when the document is
    filtered), so segment counts sum to input docs exactly.
    Validators skip b"".
    """
    results = []
    for line in lines:
        if isinstance(line, bytes):
            line = line.strip()
            if not line:
                continue
        else:
            line = line.strip()
            if not line:
                continue
            line = line.encode()
        result = tokenizer.process_document(line)
        if result is None:
            results.append(b"")
        else:
            results.append(
                json.dumps(result, separators=(",", ":")).encode())
    return results
