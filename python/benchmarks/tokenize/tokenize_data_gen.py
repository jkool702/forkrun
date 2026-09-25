"""Synthetic LLM training corpus generator (W-PY25).

Simulates raw text documents for LLM training data preparation.
Text follows a Zipf-like mix: common words, domain terms,
sub-word-friendly forms, rare OOV words, and generated tokens.

Deterministic (seeded) for reproducible benchmarks. The vocabulary
is written alongside the corpus; every competitor loads the SAME
.vocab file (single source of truth — no duplicated construction).
"""

import json
import random

SEED = 2024

COMMON_WORDS = [
    "the", "of", "and", "to", "in", "a", "is", "that", "for", "it",
    "with", "as", "was", "on", "are", "by", "this", "be", "have",
    "from", "not", "but", "they", "his", "she", "which", "one", "you",
    "had", "we", "all", "her", "there", "would", "their", "will",
    "can", "out", "other", "were", "do", "has", "been", "no", "when",
    "who", "make", "more", "if", "time", "way", "about", "many",
    "then", "them", "write", "like", "so", "these", "long", "down",
    "what", "some", "into", "could", "years", "two", "over", "may",
    "just", "know", "new", "any", "first", "than", "people",
]

DOMAIN_TERMS = [
    "model", "training", "inference", "token", "attention",
    "transformer", "gradient", "backpropagation", "embedding", "layer",
    "neuron", "weight", "learning", "dataset", "feature", "neural",
    "network", "activation", "batch", "epoch", "optimization",
    "regularization", "dropout", "recurrent", "convolution", "pooling",
    "vocabulary", "tokenizer", "subword", "bytepair", "encoding",
    "decoding", "decode", "parameter", "hyperparameter", "learning_rate",
    "loss", "accuracy", "validation", "overfitting", "underfitting",
    "generalization",
]

RARE_WORDS = [
    "antidisestablishmentarianism",
    "pneumonoultramicroscopicsilicovolcanoconiosis",
    "hippopotomonstrosesquippedaliophobia",
    "supercalifragilisticexpialidocious",
    "floccinaucinihilipilification",
    "pseudopseudohypoparathyroidism",
    "xenotransplantation",
    "deoxyribonucleic",
    "electroencephalography",
]

SUBWORD_UNITS = [
    "ing", "ed", "ly", "tion", "ness", "ment", "able", "ible", "ful",
    "less", "er", "est", "s", "es", "un", "re", "pre", "post", "sub",
    "super",
]


def build_vocabulary():
    """Build the deterministic 30,000-token vocabulary (id -> word).

    ID 0 is reserved for UNK/PAD. Returns dict {word: id}.
    """
    vocab = {}
    for i, word in enumerate(COMMON_WORDS):
        vocab[word] = i + 1
    next_id = len(COMMON_WORDS) + 1
    for word in DOMAIN_TERMS:
        if word not in vocab:
            vocab[word] = next_id
            next_id += 1
    for word in SUBWORD_UNITS:
        if word not in vocab:
            vocab[word] = next_id
            next_id += 1
    for word in RARE_WORDS:
        if word not in vocab:
            vocab[word] = next_id
            next_id += 1
    while next_id < 30000:
        word = "tok%05d" % next_id
        vocab[word] = next_id
        next_id += 1
    return vocab


def generate_document(rng, doc_id, min_words=50, max_words=500):
    """Generate one synthetic document (Zipf-like mix)."""
    n_words = rng.randint(min_words, max_words)
    words = []
    for _ in range(n_words):
        r = rng.random()
        if r < 0.60:
            words.append(rng.choice(COMMON_WORDS))
        elif r < 0.85:
            words.append(rng.choice(DOMAIN_TERMS))
        elif r < 0.92:
            stem = rng.choice(COMMON_WORDS[:20])
            words.append(stem + rng.choice(SUBWORD_UNITS))
        elif r < 0.95:
            words.append(rng.choice(RARE_WORDS))
        else:
            words.append("tok%05d" % rng.randint(1, 30000))
    return {
        "doc_id": doc_id,
        "text": " ".join(words),
        "source": rng.choice(["web", "book", "code", "wiki", "paper"]),
        "lang": "en",
        "timestamp": 1700000000 + rng.randint(0, 86400 * 365),
    }


def generate_corpus(path, n_docs, malformed_pct=0.0,
                      min_words=50, max_words=500):
    """Generate a JSONL corpus + sidecar .vocab file (deterministic).

    malformed_pct: percentage of garbage/empty lines (default 0.0,
    used only for robustness checks — the benchmark runs clean).
    Returns (corpus_path, vocab_path).
    """
    vocab = build_vocabulary()
    rng = random.Random(SEED)
    with open(path, "w") as fh:
        for i in range(n_docs):
            if rng.random() * 100 < malformed_pct:
                if rng.random() < 0.5:
                    fh.write("{garbage %d\n"
                             % rng.randint(0, 999999))
                else:
                    fh.write("\n")
                continue
            doc = generate_document(rng, i, min_words, max_words)
            fh.write(json.dumps(doc, separators=(",", ":")) + "\n")
    vocab_path = path + ".vocab"
    with open(vocab_path, "w") as fh:
        for word, token_id in sorted(vocab.items(),
                                     key=lambda kv: kv[1]):
            fh.write("%d\t%s\n" % (token_id, word))
    return path, vocab_path
