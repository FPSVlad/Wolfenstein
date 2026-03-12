import argparse

from .interpreter import Interpreter, run_repl


def main():
    p = argparse.ArgumentParser(description='Fortran 77 interpreter (subset)')
    p.add_argument('file', nargs='?', help='Fortran source file')
    p.add_argument('-e', '--exec', dest='code', help='Execute source string')
    args = p.parse_args()

    intr = Interpreter()
    if args.code:
        intr.run_source(args.code)
    elif args.file:
        intr.run_file(args.file)
    else:
        run_repl()


if __name__ == '__main__':
    main()
