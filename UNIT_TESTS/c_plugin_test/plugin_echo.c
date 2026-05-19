#include <stdio.h>
int plugin_echo(int argc, char **argv) {
    for (int i = 0; i < argc; i++) printf("%s\n", argv[i]);
    return 0;
}
