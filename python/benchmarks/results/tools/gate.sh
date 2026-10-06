#!/bin/bash
cd /mnt/ramdisk/forkrun/python
timeout 2400 python3 -m unittest discover -s tests -p "test_*.py" > /tmp/opencode/g1.txt 2>&1
FORKRUN_CLEANROOM=1 timeout 2400 python3 -m unittest discover -s tests -p "test_*.py" > /tmp/opencode/g1on.txt 2>&1
echo DONE > /tmp/opencode/g.done
