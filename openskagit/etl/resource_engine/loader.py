import json
from pathlib import Path

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "resource_manifest.json"

class ResourceManifest:
    def __init__(self):
        with open(MANIFEST_PATH, "r") as f:
            self.data = json.load(f)

    def resources(self):
        return self.data.items()
