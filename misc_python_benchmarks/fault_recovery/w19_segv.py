
import ctypes
def payload(batch):
    if batch.batch_index == 0:
        ctypes.string_at(0)
    return bytes(batch.data).upper()
