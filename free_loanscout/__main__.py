"""Lets the package run as a program: python -m free_loanscout run ...

It hands the command-line arguments to cli.main and exits with the number
main returns: 0 when the run went well, otherwise one of the EXIT_ codes at
the top of cli.py (no matches, bad settings, nothing new, stopped...).
"""

from .cli import main

raise SystemExit(main())
