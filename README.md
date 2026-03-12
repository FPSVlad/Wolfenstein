# Fortran 77 Interpreter (Python 3.9)

Модульный интерпретатор Fortran 77 без внешних зависимостей.

## Структура

- `fortran77/lexer.py` — fixed-form препроцессинг, комментарии, метки, токенизация выражений.
- `fortran77/parser.py` — парсер программы/операторов/выражений.
- `fortran77/ast.py` — AST узлы.
- `fortran77/interpreter.py` — рантайм, встроенные функции, I/O, REPL.

## Запуск

```bash
python -m fortran77 path/to/program.f
python -m fortran77 -e "      PROGRAM P\n      WRITE(*,*) 'HI'\n      END"
python -m fortran77
```
