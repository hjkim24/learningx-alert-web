"""DESIGN.md is the source of truth for color tokens; app.css and the Figma
plugin must carry the same values."""

import re

from django.conf import settings
from django.test import SimpleTestCase

ROOT = settings.BASE_DIR


def _read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class DesignTokenSyncTests(SimpleTestCase):
    def setUp(self):
        self.design = {
            name: value.upper()
            for name, value in re.findall(r"\| `--([a-z0-9-]+)` \| `(#[0-9A-Fa-f]{6})`", _read("DESIGN.md"))
        }

    def test_design_md_lists_the_palette(self):
        for name in ("brand", "brand-strong", "brand-soft", "ink", "muted", "urgent", "lake", "clay"):
            self.assertIn(name, self.design)

    def test_css_matches_design_md(self):
        css = {
            name: value.upper()
            for name, value in re.findall(r"^\s+--([a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", _read("static/app.css"), re.M)
        }
        for name, value in self.design.items():
            self.assertEqual(css.get(name), value, name)

    def test_figma_plugin_matches_design_md(self):
        plugin_path = ROOT / "tools" / "figma-design-system" / "code.js"
        if not plugin_path.exists():
            self.skipTest("plugin not present in this build")
        plugin = {
            name.strip('"'): value.upper()
            for name, value in re.findall(r'^\s+"?([a-z0-9-]+)"?: "(#[0-9A-Fa-f]{6})"', plugin_path.read_text(encoding="utf-8"), re.M)
        }
        self.assertEqual(plugin, self.design)
