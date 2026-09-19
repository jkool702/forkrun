#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <sys/types.h>
#include "forkrun_plugin.h"

int forkrun_use_ctx = 1;

int plugin_cfg_marker(int argc, char **argv, void *ctx_ptr) {
    (void)ctx_ptr;
    for (int i = 0; i < argc; i++) {
        if (strcmp(argv[i], "MARKER") == 0) return 1;
    }
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
