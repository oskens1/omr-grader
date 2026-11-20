"""Registration and review checks for the optional V5.3 printed-card mode."""
from collections import Counter
import re

import cv2
import numpy as np

import detection_0914 as detector

MODE = 'PRINTED_RECOVERY'
MAX_QUESTION = 15


def expected_classes(text):
    classes = set(re.split(r'[\s,，、]+', text.strip())) if text.strip() else set()
    if any(not re.fullmatch(r'[123][0-9]{2}', value) for value in classes):
        raise ValueError('班級請填三位數字，例如 202、203')
    return classes


def recover_timing(gray):
    ids, observed = detector.timing_groups(gray)
    if not 23 <= len(observed) <= 24:
        raise ValueError('需要 23 至 24 條實測黑條才能復原中間缺列')
    dy = np.diff(observed[:, 1])
    pitch = np.median(dy)
    steps = np.rint(dy / pitch).astype(int)
    if (steps.min() < 1 or steps.max() > 3 or steps.sum() != 24
            or np.max(abs(dy / (steps * pitch) - 1)) > .12):
        raise ValueError('黑條間距不支持 25 列')
    rows = np.r_[0, np.cumsum(steps)]
    missing = sorted(set(range(25)) - set(rows))
    bars = np.column_stack([np.interp(np.arange(25), rows, observed[:, i]) for i in range(2)])
    return ids, bars, missing


def check_used_block(check, geometry, missing):
    """Validate the original first-block coverage and reconstructed rows."""
    centers = np.asarray(geometry['centers'])
    observed = check.get('observed', [])
    first = [box for box in observed if box['column'] < 5]
    if not first:
        return {'passed': False, 'matched': 0}
    rows = np.bincount([box['row'] for box in first], minlength=25)
    cols = np.bincount([box['column'] for box in first], minlength=5)
    disagreements = set(check.get('disagreements', []))
    errors = [np.linalg.norm(centers[box['row'], box['column']] - [box['x'], box['y']])
              for box in first]
    min_row, min_col = int(rows.min()), int(cols.min())
    p95, maximum = float(np.percentile(errors, 95)), float(max(errors))
    passed = (len(first) >= 100 and min_row >= 3 and min_col >= 15
              and not any(index % 20 < 5 for index in disagreements)
              and p95 <= 3 and maximum <= 5)
    corroboration = {}
    for row in missing:
        blocks = set()
        for box in observed:
            col = box['column']
            if box['row'] == row and col >= 5 and row * 20 + col not in disagreements:
                if np.linalg.norm(centers[row, col] - [box['x'], box['y']]) <= 3:
                    blocks.add(col // 5 + 1)
        corroboration[row + 1] = sorted(blocks)
        passed &= len(blocks) >= 2
    return dict(passed=bool(passed), matched=len(first), minimum_per_row=min_row,
                minimum_per_column=min_col, after_p95=p95, after_max=maximum,
                recovered_row_corroboration=corroboration)


def _attempt_orientation(gray, core, recover):
    def versions():
        yield 'none', gray
        yield 'horizontal', cv2.morphologyEx(gray, cv2.MORPH_OPEN, np.ones((1, 3), np.uint8))
        for gain in (1.3, 1.6, 2.0):
            yield f'contrast {gain}', np.clip(255-(255-gray.astype(float))*gain, 0, 255).astype(np.uint8)

    contrast_candidates = []
    attempts = []
    for name, prepared in versions():
        try:
            missing = []
            timing_data = None
            if recover:
                ids, bars, missing = recover_timing(prepared)
                timing_data = (ids, bars)
            geometry = detector.locate(prepared, core, timing_data=timing_data)
            check = check_used_block(detector.check_boxes(gray, geometry, {}), geometry, missing)
        except (ValueError, cv2.error) as exc:
            attempts.append(dict(preprocess=name, error=str(exc)))
            continue
        attempts.append(dict(preprocess=name, check=check))
        if not check['passed']:
            continue
        choice = dict(geometry=geometry, check=check, preprocess=name,
                      recovered_rows=[row+1 for row in missing])
        if not name.startswith('contrast'):
            return choice, attempts
        contrast_candidates.append(choice)
    for index, first in enumerate(contrast_candidates):
        a = np.asarray(first['geometry']['centers'])
        for other in contrast_candidates[index+1:]:
            b = np.asarray(other['geometry']['centers'])
            if np.max(np.linalg.norm(a-b, axis=2)) <= 1:
                return dict(first, agreement_with=other['preprocess']), attempts
    return None, attempts


def locate(image, core, audit):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    directions = ((0, gray), (180, cv2.rotate(gray, cv2.ROTATE_180)))
    audit['geometry_attempts'] = []
    for recover in (False, True):
        accepted = []
        for angle, oriented in directions:
            result, attempts = _attempt_orientation(oriented, core, recover)
            audit['geometry_attempts'].append(dict(rotation=angle, recovery=recover, attempts=attempts))
            if result:
                accepted.append((angle, oriented, result))
        if len(accepted) > 1:
            raise ValueError('兩個方向皆通過，須確認卡片方向')
        if accepted:
            angle, oriented, result = accepted[0]
            audit.update(rotation=angle, preprocess=result['preprocess'],
                         geometry_check=result['check'], recovered_rows=result['recovered_rows'])
            if 'agreement_with' in result:
                audit['agreement_with'] = result['agreement_with']
            debug = image if angle == 0 else cv2.rotate(image, cv2.ROTATE_180)
            return oriented, debug, result['geometry']
    raise ValueError('定位或獨立印刷框校驗未通過')


def mark_coverage(gray, question, floor):
    suspects = {}
    for letter, center in zip('ABCDE', question['centers']):
        if letter in question['answer']:
            sample = cv2.getRectSubPix(gray, (14, 4), tuple(center))
            coverage = float(np.mean(255.0 - floor - sample >= detector.MARK_LIMIT))
            if coverage < 2 / 3:
                suspects[letter] = coverage
    return suspects


def valid_sid(sid):
    return bool(re.fullmatch(r'[123][0-9]{4}', sid) and sid[-2:] != '00')


def finalize_batch(audits, grades, classes):
    """Exclude review pages from grade sheets, including both sides of a duplicate."""
    counts = Counter(row['sid'] for row in audits if valid_sid(row.get('sid', '')))
    keep = set()
    for row in audits:
        sid = row.get('sid')
        if not sid:
            continue
        if valid_sid(sid):
            if classes and sid[:3] not in classes:
                row['flags'].append('班級不在本次批改範圍')
            if counts[sid] > 1:
                row['flags'].append('學號重複，所有同號卡片均待核')
        if row['flags']:
            row['status'] = 'REVIEW'
        else:
            keep.add(row['page'])
    return [grade for grade in grades if grade['頁碼'] in keep]
