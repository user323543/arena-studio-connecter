"""Prüft, dass der schnelle Direkt-Download der EXE nirgends kaputtgeht.

Der README-Link zeigt bewusst NICHT auf ein Actions-Artifact (Zip über den
Artifact-Dienst, langsam), sondern auf das Release-Asset "latest" – das liefert
GitHub direkt über das CDN aus.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "build-exe.yml"

DIRECT_DOWNLOAD_RE = re.compile(
    r"https://github\.com/[^/\s]+/[^/\s]+/releases/latest/download/ArenaStudioConnector\.exe"
)


class DownloadLinkTest(unittest.TestCase):
    def test_readme_has_direct_download_link(self):
        text = README.read_text(encoding="utf-8")
        matches = DIRECT_DOWNLOAD_RE.findall(text)
        self.assertTrue(matches, "README enthält keinen Direkt-Download-Link zur EXE")
        # Kleiner blauer Text oben = HTML-Link mit <sub>, damit er unauffällig bleibt.
        self.assertIn("<sub>", text, "Der kleine Download-Text oben fehlt")

    def test_workflow_publishes_the_same_url(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("releases/latest/download/ArenaStudioConnector.exe", text)
        self.assertIn("gh release create latest", text)
        # Fallback über Actions-Artifact bleibt erhalten.
        self.assertIn("actions/upload-artifact", text)


if __name__ == "__main__":
    unittest.main()
