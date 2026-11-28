CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wno-unused-parameter -std=gnu11 -fPIC -pthread
SAN_CFLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined
TSAN_CFLAGS := -O1 -g -fno-omit-frame-pointer -fsanitize=thread

DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
BIN := prefault_pipeline

all: $(BIN)

$(BIN): prefault_pipeline.c
	$(CC) $(CFLAGS) -o $@ prefault_pipeline.c -pthread

# isolated sanitizer outputs (do not clobber `all` artifact)
asan-ubsan: prefault_pipeline.c
	$(CC) $(SAN_CFLAGS) -o $(BIN)-asan prefault_pipeline.c -pthread -fsanitize=address,undefined
tsan: prefault_pipeline.c
	$(CC) $(TSAN_CFLAGS) -o $(BIN)-tsan prefault_pipeline.c -pthread -fsanitize=thread

clean:
	rm -f $(BIN) $(BIN)-asan $(BIN)-tsan

.PHONY: all clean asan-ubsan tsan
