"""Desktop adapter for the optional printed-card modes."""
import cv2
import detection_0914 as detector
import detection_recovery as recovery
from omr_processor import OMRProcessor as LegacyOMR


class OMRProcessor(LegacyOMR):
    def set_card_mode(self, mode):
        if mode in ('PRINTED_0914', recovery.MODE):
            self.card_mode = mode
        else:
            super().set_card_mode(mode)

    def process_image(self, img_array, filename, id_map, q_config, ans_key):
        self.last_audit = {'flags': []}
        if self.card_mode not in ('PRINTED_0914', recovery.MODE):
            return super().process_image(img_array, filename, id_map, q_config, ans_key)
        use_recovery = self.card_mode == recovery.MODE
        debug = img_array.copy()
        try:
            max_question = recovery.MAX_QUESTION if use_recovery else 10
            if not ans_key or any(not isinstance(q, int) or not 1 <= q <= max_question for q in ans_key):
                message = ('定位復原模式限第 1～15 題' if use_recovery else
                           '9/14 trial supports Q1..Q10 only; use legacy modes for longer exams')
                raise ValueError(message)
            if use_recovery:
                gray, oriented, geometry = recovery.locate(img_array, self, self.last_audit)
                debug = detector.draw(oriented, geometry, 'V5.3 TRIAL - CHECK BEFORE USE')
            else:
                gray = cv2.cvtColor(img_array, cv2.COLOR_BGR2GRAY)
                geometry = detector.locate(gray, self)
                check = detector.check_boxes(gray, geometry, {})
                self.last_audit['geometry_check'] = check
                debug = detector.draw(img_array, geometry, 'V5.2 TRIAL - CHECK BEFORE USE')
                if not check['passed']:
                    raise ValueError('Independent box check failed')
            identity = detector.identify(gray, geometry, self)
            marks, floor = detector.answer_marks(gray, geometry, self, max(ans_key))
            sid = identity['raw_sid']
            flags = self.last_audit['flags']
            if '?' in sid or (use_recovery and not recovery.valid_sid(sid)):
                flags.append('學號不明：請由原卡確認；不可直接當正式成績')
            if use_recovery:
                self.last_audit['sid'] = sid
            answers = {q['q']: q['answer'] for q in marks if q['answer']}
            for q in marks:
                if q['q'] not in ans_key:
                    continue
                issues = []
                if q['uncertain']: issues.append('淡痕/擦痕 ' + q['uncertain'])
                if q['unstable']: issues.append('微移敏感 ' + q['unstable'])
                if not q['answer'] and not use_recovery: issues.append('空白')
                if use_recovery:
                    weak_coverage = recovery.mark_coverage(gray, q, floor)
                    if weak_coverage:
                        q['weak_coverage'] = weak_coverage
                        issues.append('墨跡分布需覆核 ' + ''.join(weak_coverage))
                if q_config.get(q['q'], {}).get('type') == 'STRICT' and len(q['answer']) > 1:
                    issues.append('單選複塗')
                if issues: flags.append(f"Q{q['q']}: " + ', '.join(issues))
                for letter, point, state in zip('ABCDE', q['centers'], q['states']):
                    x, y = map(round, point)
                    if letter in str(ans_key[q['q']]) and ans_key[q['q']] != 'BONUS':
                        cv2.rectangle(debug, (x-12,y-8), (x+12,y+8), (0,180,0), 1)
                    cv2.circle(debug, (x,y), 6, {'marked':(0,0,255),'blank':(255,80,0),'uncertain':(0,150,255)}[state], 2)
            for row, points in enumerate(identity['centers']):
                for digit, point in enumerate(points):
                    if row == 0 and digit not in (1,2,3): continue
                    x, y = map(round, point)
                    color = (0,0,255) if str(digit) == sid[row] else (180,0,180)
                    cv2.rectangle(debug,(x-7,y-2),(x+7,y+2),color,1)
            parts = {}; total = 0.0
            for q, key in ans_key.items():
                cfg = q_config[q]; part = cfg.get('part','Part1')
                entry = parts.setdefault(part, {'earned':0.0,'full':0.0})
                full = float(cfg['score'])
                earned = self.calculate_points(cfg['type'], full, ''.join(sorted(answers.get(q,''))),
                                               ''.join(sorted(str(key))) if key != 'BONUS' else key,
                                               int(cfg.get('options',5)), cfg.get('remark',''))
                entry['earned'] += earned; entry['full'] += full; total += earned
            total = round(total,2)
            self.draw_score_on_img(debug,sid,parts,total)
            if flags: cv2.putText(debug,'REVIEW REQUIRED',(35,110),cv2.FONT_HERSHEY_SIMPLEX,1,(0,0,255),2)
            self.last_audit.update(identity=identity, questions=marks, background_floor=floor)
            return (sid,answers,total),debug,'REVIEW' if flags else 'Success'
        except (ValueError, cv2.error) as exc:
            self.last_audit['flags'].append('定位/格式未通過，不計分：'+str(exc))
            return None, debug, 'Locate Fail: '+str(exc)
