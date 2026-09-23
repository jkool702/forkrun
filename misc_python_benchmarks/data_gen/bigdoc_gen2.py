import sys, json, random
sys.path.insert(0, '/mnt/ramdisk/forkrun/python/benchmarks')
from tokenize_data_gen import COMMON_WORDS, DOMAIN_TERMS, RARE_WORDS, SUBWORD_UNITS
rng = random.Random(777)
with open('/tmp/bigdocs2.jsonl', 'w') as fh:
    for i in range(3000):
        n_words = rng.randint(500, 800)
        words = []
        for _ in range(n_words):
            r = rng.random()
            if r < 0.60: words.append(rng.choice(COMMON_WORDS))
            elif r < 0.85: words.append(rng.choice(DOMAIN_TERMS))
            elif r < 0.92: words.append(rng.choice(COMMON_WORDS[:20]) + rng.choice(SUBWORD_UNITS))
            elif r < 0.95: words.append(rng.choice(RARE_WORDS))
            else: words.append('tok%05d' % rng.randint(1, 30000))
        fh.write(json.dumps({'doc_id': i, 'text': ' '.join(words), 'source': 'web', 'lang': 'en', 'timestamp': 1700000000}) + '\n')
import os
print('bytes:', os.path.getsize('/tmp/bigdocs2.jsonl'))
