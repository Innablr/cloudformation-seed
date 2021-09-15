import os
from pathlib import Path

VERSION = Path(os.path.join('..', 'version.txt')).read_text().strip()
