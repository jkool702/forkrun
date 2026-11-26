CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -Wno-unused-parameter -fPIC -pthread
LDFLAGS ?= -shared -pthread

# CK-1.2: explicit output variable so callers (mandatory preflight, sanitizer
# harness, tests) can build into an ISOLATED temporary artifact without
# touching a pre-existing/instrumented artifact. `make clean` removes only
# $(DI_OUTPUT).
DI_OUTPUT ?= ../libdist_ingest.so

# CK-1: memory policy goes through the Linux syscall interface only
# (SYS_mbind/__NR_mbind; SYS_move_pages). The engine calls NO libnuma
# library functions; libnuma-dev is NOT required and libnuma is NOT linked.
# No syscall-interface-absent fallback exists (no libnuma wrapper fallback).

all: $(DI_OUTPUT)

$(DI_OUTPUT): dist_ingest.c dist_ingest.h
	$(CC) $(CFLAGS) -o $@ dist_ingest.c $(LDFLAGS)

clean:
	rm -f $(DI_OUTPUT)

.PHONY: all clean
