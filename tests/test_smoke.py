import io
import unittest

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fortran77 import Interpreter


class SmokeTests(unittest.TestCase):
    def run_src(self, src, stdin=''):
        out = io.StringIO()
        inp = io.StringIO(stdin)
        Interpreter(stdin=inp, stdout=out).run_source(src)
        return out.getvalue()

    def test_sample(self):
        src = '''
      PROGRAM HELLO
      INTEGER I, N
      REAL X, Y
      CHARACTER*20 NAME
      WRITE(*,*) 'Enter your name:'
      READ(*,*) NAME
      WRITE(*,*) 'Hello, ', NAME
      N = 2
      DO 10 I = 1, N
         X = I * 2.5
         Y = SQRT(X)
         WRITE(*,100) I, X, Y
  10  CONTINUE
  100 FORMAT('I=', I3, ' X=', F6.2, ' Y=', F8.4)
      END
'''
        out = self.run_src(src, 'Alice\n')
        self.assertIn('Hello,  Alice', out)
        self.assertIn('I=  1 X=  2.50 Y=', out)

    def test_subroutine_by_reference(self):
        src = '''
      PROGRAM P
      INTEGER A
      A = 3
      CALL INC(A)
      WRITE(*,*) A
      END
      SUBROUTINE INC(X)
      INTEGER X
      X = X + 5
      END
'''
        out = self.run_src(src)
        self.assertIn('8', out)


if __name__ == '__main__':
    unittest.main()
