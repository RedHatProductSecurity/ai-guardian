#!/usr/bin/env python3

import sys


def main():
    """Delegate to the dependency-light hook runtime."""
    from ai_guardian_hook_runtime import main as runtime_main

    return runtime_main()


if __name__ == "__main__":
    sys.exit(main())
