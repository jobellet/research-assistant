#!/usr/bin/env python3
"""
Integration test suite for the newly integrated Grant Toolkit modules:
- audit_module (prose_auditor, number_auditor)
- toolkit_module (pdf_comments, schedule_generator, figure_fit, measure_pages)
- docx_module (docxkit, zotero_fields)
- server_module Grant Toolkit REST endpoints
"""
import os
import sys
import json
import unittest

# Import integrated modules
from audit_module.prose_auditor import audit_prose
from audit_module.number_auditor import audit_numbers
from toolkit_module.schedule_generator import generate_schedule_chart
from toolkit_module.figure_fit import calculate_figure_fit


class TestGrantToolkitIntegration(unittest.TestCase):

    def test_prose_auditor(self):
        sample_draft = """
        Moreover, the proposed experiments will optimize our recording pipeline.
        Importantly, this approach requires no additional hardware.
        Furthermore, we expect to record 150 neurons per session.
        Together, these results will demonstrate strong performance.
        The data is not always easy to interpret.
        """
        res = audit_prose(sample_draft)
        self.assertIn("word_count", res)
        self.assertIn("connectives", res)
        self.assertGreater(res["connectives"]["total"], 0)
        self.assertIn("empty_negatives", res)
        self.assertIn("sentence_rhythm", res)

    def test_number_auditor(self):
        sample_paras = [
            "We plan 12 recording sessions across 4 macaques.",
            "Each monkey undergoes 3 sessions per animal with 4 animals.",
            "In month 12 to 24 we record 100 neurons, whereas in month 30 we record 150 neurons.",
            "Phase 3 extends into month 40."
        ]
        res = audit_numbers(sample_paras, horizon=36)
        self.assertEqual(res["paragraph_count"], 4)
        self.assertIn("quantity_discrepancies", res)
        self.assertIn("timeline", res)
        self.assertIn(40, res["timeline"]["overruns"])
        self.assertGreater(len(res["animal_math"]), 0)
        self.assertEqual(res["animal_math"][0]["total_sessions"], 12)

    def test_schedule_generator(self):
        out_img = "test_work_schedule.png"
        if os.path.exists(out_img):
            os.remove(out_img)
        res = generate_schedule_chart(output_path=out_img)
        self.assertTrue(os.path.exists(out_img))
        self.assertGreater(res["width_px"], 0)
        self.assertGreater(res["height_px"], 0)
        if os.path.exists(out_img):
            os.remove(out_img)

    def test_figure_fit(self):
        out_img = "test_fig.png"
        # Create a small dummy image for testing
        from PIL import Image
        img = Image.new('RGB', (800, 600), color='white')
        img.save(out_img)

        res = calculate_figure_fit([out_img], text_width_cm=16.0, text_height_cm=24.0, width_frac=1.0)
        self.assertEqual(len(res["figures"]), 1)
        fig_res = res["figures"][0]
        self.assertEqual(fig_res["status"], "ok")
        self.assertEqual(fig_res["rendered_width_cm"], 16.0)
        self.assertEqual(fig_res["rendered_height_cm"], 12.0)
        self.assertEqual(fig_res["page_fraction"], 0.5)

        if os.path.exists(out_img):
            os.remove(out_img)


if __name__ == "__main__":
    unittest.main()
