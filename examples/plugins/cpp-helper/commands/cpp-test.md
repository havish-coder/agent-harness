---
description: build a C++ file with your compiler and run it; fix what fails
argument-hint: FILE.cpp
---
Build and run the C++ file $1 with {{compiler}} (standard {{standard}}, all warnings: {{warnings}}).

1. Build it. With g++ or clang++: `{{compiler}} -std={{standard}} -g -Wall -Wextra -o out $1` (without `-Wall -Wextra` if warnings are false). With cl: `cl /std:{{standard}} /EHsc /W4 $1`.
2. If it doesn't compile, read the first error, fix the code, and build again.
3. Run the program and show what it printed. If it crashes or prints something wrong, find out why and fix it.
4. Say in two or three lines what you changed, if anything.
