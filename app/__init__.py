import os
import sys
import tempfile

# macOS's temp folder (/var/folders/...) is a link into /private/var: a CLI started in a folder
# of KOLONİ's there says its cwd by the real path, so every temp folder is made by that one
# (and `CLI_TEMP` finds it in what the CLI says). Not on Windows: there realpath would turn a
# short name (RUNNER~1) long, and a child's cwd is as it was given.
if sys.platform == "darwin":
    tempfile.tempdir = os.path.realpath(tempfile.gettempdir())
