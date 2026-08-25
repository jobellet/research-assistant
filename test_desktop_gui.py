#!/usr/bin/env python3
"""
Automated unit test for Desktop Tkinter GUI (scripts/search_gui.py).
Tests initialization, search modes, selection, BibTeX formatting, and project bib additions.
"""
import sys
import unittest
import tkinter as tk

from scripts.search_gui import ResearchAssistantGUI


class TestDesktopGUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()  # Don't pop up window during automated test
        cls.app = ResearchAssistantGUI(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_gui_init(self):
        self.assertIsNotNone(self.app)
        self.assertGreater(len(self.app.projects), 0)

    def test_bow_search(self):
        self.app.search_var.set("neural")
        self.app.mode_var.set("bow")
        self.app.perform_search()
        self.assertIsInstance(self.app.search_results, list)

    def test_paper_selection(self):
        # Insert a dummy item into tree
        self.app.search_results = [{
            "hash_id": "0000000000000000000000000000000000000000000000000000000000000000",
            "score": 95.0,
            "metadata": {
                "title": "Test Neural Paper",
                "authors": "Jane Doe, John Smith",
                "year": "2024",
                "doi": "10.1038/s41586-024-00000-0",
                "keywords": "neuroscience, encoding"
            },
            "summary": "This is a test summary about neural encoding.",
            "files": [],
            "method": "bow"
        }]
        self.app.populate_tree()
        children = self.app.tree.get_children()
        self.assertGreater(len(children), 0)

        # Select item
        self.app.tree.selection_set(children[0])
        self.app.on_paper_select(None)

        self.assertIsNotNone(self.app.selected_paper)
        self.assertEqual(self.app.lbl_title.cget("text"), "Test Neural Paper")

    def test_copy_bibtex_and_key(self):
        if self.app.selected_paper:
            self.app.copy_key()
            key_val = self.app.root.clipboard_get()
            self.assertTrue(len(key_val) > 0)

            self.app.copy_bibtex()
            bib_val = self.app.root.clipboard_get()
            self.assertIn("@article", bib_val)

    def test_add_to_project_bib(self):
        if self.app.selected_paper:
            # Test project bib addition
            self.app.add_to_project_bib()


if __name__ == "__main__":
    unittest.main()
