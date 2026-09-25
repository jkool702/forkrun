import sys, os; sys.path.insert(0, 'python')
_real_close = os.close
import traceback as _tb
def logged_close(fd):
    if os.environ.get("FORKRUN_DEBUG_CLOSE"):
        try:
            _real_close(2)
        except OSError:
            pass
        # log pid, fd, and abbreviated stack to a file (unbuffered)
        with open("/tmp/closes.log", "a") as fh:
            frames = _tb.extract_stack()[-4:-1]
            loc = ";".join("%s:%d" % (f.filename.split("/")[-1], f.lineno) for f in frames)
            fh.write("pid=%d close(%s) at %s\n" % (os.getpid(), fd, loc))
            fh.flush()
    return _real_close(fd)
os.close = logged_close
import forkrun
def up(b):
    return bytes(b.data).upper()
a = list(forkrun.stream(up, '/tmp/w19_smoke.txt', workers=4, nodes='@2', c_drain=True))
print('done', len(a), flush=True)
