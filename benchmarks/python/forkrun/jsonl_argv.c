/* Stage 0 forkrun side: JSONL validation via argv (copy path).
 * Validates each record minimally (braces + "id" key) and re-emits verbatim.
 * Output contract: byte-identical to input. */
#include <stdio.h>
#include <string.h>

int jsonl_parse_argv(int argc, char **argv) {
    for (int i = 0; i < argc; i++) {
        size_t n = strlen(argv[i]);
        if (n < 2 || argv[i][0] != '{' || argv[i][n - 1] != '}' ||
            strstr(argv[i], "\"id\"") == NULL)
            return 1;
        if (fwrite(argv[i], 1, n, stdout) != n) return 1;
        if (fputc('\n', stdout) != '\n') return 1;
    }
    return 0;
}
