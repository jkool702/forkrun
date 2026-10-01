import multiprocessing, logging
logger = multiprocessing.log_to_stderr(logging.DEBUG)
def sq(x): return x*x
try:
    with multiprocessing.Pool(2) as p:
        print('result:', p.map(sq, range(10)), flush=True)
except Exception as e:
    print('DIED:', type(e).__name__, str(e)[:200], flush=True)
