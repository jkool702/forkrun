#include <stdio.h>
#include <string.h>

int test_basic(int argc, char **argv) {
    size_t total = 0;
    for (int i = 0; i < argc; i++) total += strlen(argv[i]);
    printf("BASIC: batch_size=%d total_chars=%zu\n", argc, total);
    return 0;
}
