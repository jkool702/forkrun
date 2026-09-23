import multiprocessing
multiprocessing.set_start_method('fork', force=True)
def sq(x): return x*x
with multiprocessing.Pool(2) as p:
    print('pool-fork:', p.map(sq, range(10)), flush=True)
