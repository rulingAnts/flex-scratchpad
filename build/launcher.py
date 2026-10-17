"""The packaged program's entry point. PyInstaller runs its script as a bare `__main__`, so this
imports the package properly; flex_scratchpad/__main__.py itself uses relative imports and fails
as a script ("attempted relative import with no known parent package" — which a windowed build
shows in a message box nobody on a build runner can close)."""
import sys

from flex_scratchpad.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
