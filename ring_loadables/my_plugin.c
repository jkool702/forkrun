#include <stdio.h>

int my_worker(int argc, char **argv) {
    // Just count the bytes across all records in the batch
    size_t total_bytes = 0;
    for (int i = 0; i < argc; i++) {
        char *p = argv[i];
        while (*p++) total_bytes++;
    }
    // Print the batch result (forkrun's ordered mode will safely catch this!)
    printf("Processed %d items, %zu bytes total.\n", argc, total_bytes);
    return 0;
}
