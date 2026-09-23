import multiprocessing
def sq(x): return x*x
with multiprocessing.Pool(2) as p:
    print('pool-alone:', p.map(sq, range(10)), flush=True)
