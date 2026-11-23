#!/usr/bin/env python3
"""启动学生端：python run_student.py [--teacher-host 192.168.1.10]"""
import sys

from thyclass.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["student", *sys.argv[1:]]))
