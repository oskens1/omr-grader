"""Regression checks using the published synthetic cards."""
from pathlib import Path
import unittest

import cv2
import fitz
import numpy as np

import detection_0914 as detector
import detection_recovery as recovery
from omr_upgrade import OMRProcessor


ROOT = Path(__file__).resolve().parent


class RecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        samples = ROOT / 'samples'
        if not samples.is_dir():
            samples = ROOT.parent / 'samples'
        with fitz.open(samples / '合成測試卡_5頁.pdf') as doc:
            pix = doc[0].get_pixmap(dpi=200, colorspace=fitz.csGRAY)
            cls.gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
        cls.core = OMRProcessor(str(ROOT / 'assets'))
        cls.anchor = detector.locate(cls.gray, cls.core)

    def erase(self, rows):
        image = self.gray.copy()
        for row in rows:
            x, y = map(round, self.anchor['timing'][row])
            image[y-8:y+9, x-25:x+26] = 255
        return image

    def test_interior_loss_requires_printed_corroboration(self):
        for rows in ([3], [3, 5]):
            with self.subTest(rows=rows):
                image = self.erase(rows)
                ids, bars, missing = recovery.recover_timing(image)
                self.assertEqual(missing, rows)
                geometry = detector.locate(image, self.core, timing_data=(ids, bars))
                deviation = np.abs(np.asarray(self.anchor['centers']) - geometry['centers'])
                self.assertLessEqual(deviation.max(), 1)
                check = detector.check_boxes(image, geometry, {})
                self.assertTrue(recovery.check_used_block(check, geometry, missing)['passed'])
                check['observed'] = [b for b in check['observed']
                                     if b['row'] not in missing or b['column'] < 5]
                self.assertFalse(recovery.check_used_block(check, geometry, missing)['passed'])

    def test_missing_end_or_too_many_rows_rejected(self):
        for rows in ([0], [24], [3, 5, 7]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                recovery.recover_timing(self.erase(rows))

    def test_180_degree_orientation(self):
        image = cv2.cvtColor(cv2.rotate(self.gray, cv2.ROTATE_180), cv2.COLOR_GRAY2BGR)
        info = {}
        recovery.locate(image, self.core, info)
        self.assertEqual(info['rotation'], 180)

    def test_marks_with_sparse_dark_pixels_get_flagged(self):
        image = np.full((40, 80), 255, np.uint8)
        image[18:22, 23:30] = 40
        question = {'centers': [(30.5, 19.5)] * 5, 'answer': 'A'}
        self.assertEqual(set(recovery.mark_coverage(image, question, 0)), {'A'})
        image[18:22, 24:38] = 40
        self.assertFalse(recovery.mark_coverage(image, question, 0))

    def test_duplicate_and_wrong_class_excluded_from_grade_rows(self):
        audits = [{'page': i, 'sid': sid, 'flags': [], 'status': 'Success'}
                  for i, sid in enumerate(['10101', '10101', '10202', '10103'], 1)]
        audits[0]['flags'].append('Q1: 淡痕')
        grades = [{'頁碼': row['page']} for row in audits]
        self.assertEqual(recovery.finalize_batch(audits, grades, {'101'}), [{'頁碼': 4}])
        self.assertEqual([row['status'] for row in audits], ['REVIEW'] * 3 + ['Success'])


if __name__ == '__main__':
    unittest.main()
