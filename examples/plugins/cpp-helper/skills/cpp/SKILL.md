---
description: Writing, building and fixing C++ code (compiler, standard, warnings, common pitfalls)
---
How to work on C++ here. The user's compiler is {{compiler}}, the standard is {{standard}}, and compiling with all warnings on is {{warnings}}.

Writing code:
- Write standard {{standard}}: `std::vector`, `std::string`, `std::unique_ptr`, range-based `for`, `auto` where the type is obvious. No `using namespace std;` in headers.
- Put each class in a `.hpp` with an include guard (or `#pragma once`) and its code in a `.cpp`, unless the user asked for one file.
- Prefer values and references to raw pointers. A class that owns memory follows the rule of zero (let `std::unique_ptr` or a container own it).
- Give a small `main()` that shows the code working when the user didn't say how it will be used.

Building:
- g++ or clang++: `{{compiler}} -std={{standard}} -O0 -g -Wall -Wextra -o NAME NAME.cpp` (drop `-Wall -Wextra` if warnings are false).
- cl: `cl /std:{{standard}} /EHsc /W4 NAME.cpp` (`/std:` takes `c++17`, `c++20` or `c++latest`).
- Build after every change, and read the first error first: the later ones are often caused by it.

Common pitfalls to check for: reading past the end of a vector (use `.at()` while debugging), a reference to a local returned from a function, `int` overflow in sizes (use `std::size_t`), signed/unsigned comparison warnings, a missing `#include`, uninitialised variables.
