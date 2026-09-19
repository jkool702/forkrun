/* Stage 0 engine-capability probe for stdin delivery (ctx-less echo). */
#include <unistd.h>
#include <sys/types.h>
int probe_stdin_live(int argc, char **argv) {
    (void)argc; (void)argv;
    char buf[65536];
    for (;;) {
        ssize_t n = read(STDIN_FILENO, buf, sizeof(buf));
        if (n < 0) return 1;
        if (n == 0) break;
        size_t off = 0;
        while (off < (size_t)n) {
            ssize_t w = write(STDOUT_FILENO, buf + off, (size_t)n - off);
            if (w <= 0) return 1;
            off += (size_t)w;
        }
    }
    return 0;
}
