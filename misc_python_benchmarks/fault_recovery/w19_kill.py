
import os, signal
def payload(batch):
    os.kill(os.getpid(), signal.SIGKILL)
