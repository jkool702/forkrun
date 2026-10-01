/* Stage 0 streaming byte drain (stdin delivery): count bytes to EOF, print
 * the total. Output contract: decimal total (harness asserts == input N). */
#include <unistd.h>
#include <sys/types.h>
#include <stdio.h>
int drain_count(int argc, char **argv) {
    (void)argc; (void)argv;
    unsigned long long total = 0;
    char buf[65536];
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) break;
        total += (unsigned long long)n;
    }
    printf("%llu\n", total);
    return 0;
}
