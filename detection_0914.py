"""Detection functions ported from the 2026-09-14 pipeline.

V5.3 shares timing extraction with the optional recovery mode. The existing
locate path still requires all 25 observed bars. V5.2 provenance is kept in
detection_provenance.json.
"""
import cv2
import numpy as np
import sys
locator = sys.modules[__name__]
OPTS = 'ABCDE'
BLANK_LIMIT = 20.0
MARK_LIMIT = 60.0


def project(h, pts):
    return cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), h).reshape(-1, 2)



def timing_groups(gray):
    bw = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]
    n, _, stats, cent = cv2.connectedComponentsWithStats(bw, 8)
    bars = [cent[i] for i in range(1, n)
            if 22 <= stats[i, 2] <= 70 and 6 <= stats[i, 3] <= 24
            and stats[i, 4] / (stats[i, 2] * stats[i, 3]) > .75]
    if not bars:
        raise ValueError('no timing bars')
    # Find the densest actual x neighbourhood (avoid histogram-boundary splits).
    bars = np.array(bars)
    x = max(bars[:, 0], key=lambda x: sum(abs(bars[:, 0] - x) < 20))
    bars = bars[abs(bars[:, 0] - x) < 20]
    bars = bars[np.argsort(bars[:, 1])]
    gaps = np.where(np.diff(bars[:, 1]) > 80)[0]
    if len(gaps) != 1:
        raise ValueError('ambiguous timing groups')
    return np.split(bars, [gaps[0] + 1])


def timing(gray):
    ids, ans = timing_groups(gray)
    if len(ans) != 25:
        raise ValueError(f'answer timing count {len(ans)} != 25')
    dy = np.diff(ans[:, 1])
    if np.max(abs(dy / np.median(dy) - 1)) > .12:
        raise ValueError('irregular timing spacing')
    return ids, ans



def trace_line(gray, ylo, yhi, xmin):
    ylo, yhi = max(0, int(ylo)), min(gray.shape[0], int(yhi))
    xmin = max(0, int(xmin))
    roi = gray[ylo:yhi, xmin:]
    bw = cv2.threshold(roi, 220, 255, cv2.THRESH_BINARY_INV)[1]
    short = cv2.morphologyEx(bw, cv2.MORPH_OPEN, np.ones((1, 15), np.uint8))
    seeds = cv2.HoughLinesP(short, 1, np.pi / 1800, 100,
                            minLineLength=350, maxLineGap=25)
    if seeds is None:
        raise ValueError('no long line seed')
    candidates = []
    xx = np.arange(roi.shape[1])
    for x1, y1, x2, y2 in seeds[:, 0]:
        if abs(x2 - x1) < 350 or abs((y2-y1)/(x2-x1)) > .04:
            continue
        slope = (y2 - y1) / (x2 - x1)
        yy = np.rint(y1 + slope * (xx-x1)).astype(int)
        offsets = np.arange(-5, 6)
        sy = np.clip(yy[None, :] + offsets[:, None], 0, roi.shape[0]-1)
        ink = np.maximum(0, 230.0 - roi[sy, xx])
        strength = ink.max(axis=0)
        support = (strength > 35).astype(np.uint8)[None, :]
        joined = cv2.morphologyEx(support, cv2.MORPH_CLOSE, np.ones((1, 11), np.uint8))[0]
        runs = np.where(np.diff(np.r_[0, joined, 0]) != 0)[0].reshape(-1, 2)
        if not len(runs):
            continue
        lo, hi = max(runs, key=lambda r: r[1]-r[0])
        valid = (strength[lo:hi] > 35)
        x = xx[lo:hi][valid]
        weights = ink[:, lo:hi][:, valid]
        y = (sy[:, lo:hi][:, valid] * weights).sum(axis=0) / weights.sum(axis=0)
        if len(x) < 850:
            continue
        # Robust regression ignores dirt, crossing strokes and missing pixels.
        coef = np.polyfit(x, y, 1)
        for _ in range(3):
            keep = abs(y - np.polyval(coef, x)) < 2.5
            coef = np.polyfit(x[keep], y[keep], 1)
        coverage = float(valid.mean())
        rms = float(np.sqrt(np.mean((y[keep]-np.polyval(coef, x[keep]))**2)))
        left, right = int(x[0]), int(x[-1])
        candidates.append(dict(left=[left+xmin, float(np.polyval(coef, left)+ylo)],
                               right=[right+xmin, float(np.polyval(coef, right)+ylo)],
                               width=right-left, coverage=coverage, rms=rms,
                               slope=float(coef[0])))
    if not candidates:
        raise ValueError('no full-width supported line')
    best = max(candidates, key=lambda c: c['width'] * c['coverage'] - c['rms'])
    if best['coverage'] < .95 or best['rms'] > 2:
        raise ValueError('line support gate failed')
    return best



def locate(gray, old, *, timing_data=None):
    ids, bars = timing(gray) if timing_data is None else timing_data
    spacing = float(np.median(np.diff(bars[:, 1])))
    # Search from the leftmost timing evidence. A median x clips the border
    # endpoint when the whole sheet rotates, even though every timing is found.
    xmin=float(bars[:,0].min())+10
    # Bands are defined at the LEFT timing column; allow the permitted slope
    # across the entire width, otherwise a rotated right endpoint is cropped.
    slope_margin=.04*(gray.shape[1]-xmin)
    top = trace_line(gray, bars[0,1]-4*spacing-slope_margin, bars[0,1]-spacing+slope_margin, xmin)
    bot = trace_line(gray, bars[-1,1]+.2*spacing-slope_margin, bars[-1,1]+1.4*spacing+slope_margin, xmin)
    corners = np.float32([top['left'], top['right'], bot['left'], bot['right']])
    ratio = bot['width'] / top['width']
    if not .97 <= ratio <= 1.03 or abs(top['slope']-bot['slope']) > .015:
        raise ValueError('inconsistent border geometry')
    if max(abs(corners[0,0]-corners[2,0]), abs(corners[1,0]-corners[3,0])) > 30:
        raise ValueError('border endpoints misaligned')
    h = cv2.getPerspectiveTransform(np.float32([[0,0],[1000,0],[0,1000],[1000,1000]]), corners)
    canon_bars = project(np.linalg.inv(h), bars)
    # Each timing bar supplies its own y; use its actual x when removing skew.
    canonical = np.array([(u, v) for v in canon_bars[:,1] for u in old.PRINTED_CANON_U])
    centers = project(h, canonical).reshape(25,20,2)
    return dict(corners=corners.tolist(), lines=[top,bot], ratio=ratio,
                centers=centers.tolist(), timing=bars.tolist(), id_timing=ids.tolist())



def check_boxes(gray, after, before):
    """Validate on observed printed rectangles, not darkness of filled answers.

    No observed rectangle is used to fit the grid. Association is limited to
    9 px (well below half the 33 px option spacing); missing evidence fails.
    Inner/outer contours of one rectangle are combined into one observation.
    """
    centers=np.asarray(after['centers']).reshape(-1,2)
    bw=cv2.threshold(gray,200,255,cv2.THRESH_BINARY_INV)[1]
    contours,_=cv2.findContours(bw,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    matches={}
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        if not (20<=w<=31 and 7<=h<=15 and cv2.contourArea(contour)/(w*h)>.55):
            continue
        point=np.array([x+(w-1)/2,y+(h-1)/2])
        distances=np.linalg.norm(centers-point,axis=1)
        index=int(distances.argmin())
        if distances[index]<9:
            matches.setdefault(index,[]).append(point)
    # Fixed geometric rectangle, not a learned image or a marked-card template.
    # Correlation tolerates broken outlines which have no closed contour.
    template=np.full((17,31),255,np.uint8)
    cv2.rectangle(template,(3,3),(27,13),0,1)
    correlation=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
    contour_count=len(matches)
    template_added=0
    disagreements=[]
    for index,(cx,cy) in enumerate(centers):
        x0=int(round(cx-15)); y0=int(round(cy-8))
        if x0<8 or y0<8 or x0+9>correlation.shape[1] or y0+9>correlation.shape[0]:
            continue
        window=correlation[y0-8:y0+9,x0-8:x0+9]
        _,score,_,peak=cv2.minMaxLoc(window)
        if score<.5:
            continue
        observed=np.array([x0-8+peak[0]+15,y0-8+peak[1]+8],float)
        if index in matches:
            if np.linalg.norm(np.median(matches[index],axis=0)-observed)>3:
                disagreements.append(index)
        else:
            matches[index]=[observed]
            template_added+=1
    indices=sorted(matches)
    if not indices:
        return dict(passed=False, matched=0)
    points=np.array([np.median(matches[k],axis=0) for k in indices])
    errors=np.linalg.norm(centers[indices]-points,axis=1)
    by_col=np.bincount(np.array(indices)%20,minlength=20)
    by_row=np.bincount(np.array(indices)//20,minlength=25)
    before_errors=None
    if before.get('centers') is not None:
        before_errors=np.linalg.norm(np.array(before['centers']).reshape(-1,2)[indices]-points,axis=1)
    return dict(passed=bool(not disagreements and len(indices)>=400 and min(by_col)>=15 and min(by_row)>=12
                            and np.percentile(errors,95)<=3 and max(errors)<=5),
                matched=len(indices),minimum_per_column=int(min(by_col)),minimum_per_row=int(min(by_row)),
                contour_count=contour_count,template_added=template_added,disagreements=disagreements,
                after_p95=float(np.percentile(errors,95)),after_max=float(max(errors)),
                before_p95=float(np.percentile(before_errors,95)) if before_errors is not None else None,
                before_max=float(max(before_errors)) if before_errors is not None else None,
                observed=[dict(row=k//20,column=k%20,x=float(p[0]),y=float(p[1])) for k,p in zip(indices,points)])



def draw(img, geom, label):
    out = img.copy()
    cv2.putText(out, label, (35,65), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0,0,180), 2)
    if geom.get('centers') is not None:
        for p in np.array(geom['centers']).reshape(-1,2):
            cv2.circle(out, tuple(np.rint(p).astype(int)), 5, (255,80,0), 1, cv2.LINE_AA)
    if geom.get('corners') is not None:
        pts = np.rint(geom['corners']).astype(int)
        for a,b in [(0,1),(2,3)]:
            cv2.line(out, tuple(pts[a]), tuple(pts[b]), (0,0,255), 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(out, tuple(p), 14, (0,0,255), 3, cv2.LINE_AA)
    else:
        cv2.putText(out, 'NO ACCEPTED BORDER', (35,110), cv2.FONT_HERSHEY_SIMPLEX, .8, (0,0,180), 2)
    return out



def sample(gray,point,background=255.0):
    # Subpixel-centred 14x4 window avoids the printed rectangle rails. Retain
    # raw and local-background-corrected intensities for independent review.
    patch=cv2.getRectSubPix(gray,(14,4),tuple(map(float,point)))
    return max(0.,float(background)-float(patch.mean()))



def classify(value):
    if value>=MARK_LIMIT:return 'marked'
    if value<=BLANK_LIMIT:return 'blank'
    return 'uncertain'



def identify(gray,geometry,old):
    corners=np.float32(geometry['corners'])
    h=cv2.getPerspectiveTransform(np.float32([[0,0],[1000,0],[0,1000],[1000,1000]]),corners)
    bars=np.array(geometry['id_timing'])
    canon=locator.project(np.linalg.inv(h),bars)
    # Match semantic rows by geometry, so one missing timing mark cannot shift
    # every following identity digit to a different row.
    rows=[]
    for target in old.ID_CANON_V_ROWS:
        nearest=int(np.argmin(abs(canon[:,1]-target)))
        rows.append(float(canon[nearest,1]) if abs(canon[nearest,1]-target)<8 else target)
    centers=locator.project(h,[(u,v) for v in rows for u in old.ID_CANON_U]).reshape(5,10,2)
    template=np.full((17,31),255,np.uint8)
    cv2.rectangle(template,(3,3),(27,13),0,1)
    corr=cv2.matchTemplate(gray,template,cv2.TM_CCOEFF_NORMED)
    observations=[]
    for row in range(5):
        offsets=[]
        for digit in (range(1,4) if row==0 else range(10)):
            x,y=centers[row,digit];x0=int(round(x-15));y0=int(round(y-8))
            if x0<7 or y0<7 or x0+8>corr.shape[1] or y0+8>corr.shape[0]:continue
            _,score,_,peak=cv2.minMaxLoc(corr[y0-7:y0+8,x0-7:x0+8])
            if score>=.5:
                offsets.append(np.array([x0-7+peak[0]+15,y0-7+peak[1]+8])-centers[row,digit])
        offset=np.median(offsets,axis=0) if len(offsets)>=2 else np.zeros(2)
        ok=bool(len(offsets)>=2 and np.max(abs(offset))<=6)
        if ok:centers[row]+=offset
        observations.append(dict(row=row,matched=len(offsets),offset=offset.tolist(),geometry_ok=ok))
    scores=[];digits=[];candidate=[];quality=[]
    for row in range(5):
        allowed=list(range(1,4) if row==0 else range(10))
        values=[sample(gray,centers[row,digit]) for digit in allowed]
        order=np.argsort(values)[::-1];best=float(values[order[0]]);second=float(values[order[1]])
        chosen=allowed[order[0]]
        # Reject empty and competing marks; no silent '?' -> '0' conversion.
        ok=bool(observations[row]['geometry_ok'] and best>=40 and best-second>=20 and best>=2*second)
        scores.append({str(d):round(v,3) for d,v in zip(allowed,values)})
        digits.append(str(chosen) if ok else '?');candidate.append(str(chosen))
        quality.append(dict(best=best,second=second,accepted=ok))
    return dict(raw_sid=''.join(digits),candidate_sid=''.join(candidate),centers=centers.tolist(),
                scores=scores,quality=quality,alignment=observations)



def answer_marks(gray,geometry,old,n_questions):
    centers=np.array(geometry['centers'])
    all_values=np.array([sample(gray,p) for p in centers.reshape(-1,2)])
    # There are 500 cells and at most 50 exam-choice cells. The median gives
    # the paper/scan floor without needing a trained or cloud model.
    floor=float(np.median(all_values))
    background=255-floor
    questions=[]
    for q in range(1,n_questions+1):
        row=(q-1)%25;block=(q-1)//25
        pts=centers[row,block*5:block*5+5]
        values=[sample(gray,p,background) for p in pts]
        states=[classify(v) for v in values]
        answer=''.join(OPTS[i] for i,s in enumerate(states) if s=='marked')
        uncertain=''.join(OPTS[i] for i,s in enumerate(states) if s=='uncertain')
        previous=''.join(OPTS[i] for i,p in enumerate(pts) if old._printed_fill_score(gray,*p)>old.PRINTED_DARK_TH)
        jitter=[]
        for p in pts:
            vals=[sample(gray,p+[dx,dy],background) for dx,dy in [(0,0),(-.75,0),(.75,0),(0,-.75),(0,.75)]]
            jitter.append([min(vals),max(vals)])
        unstable=''.join(OPTS[i] for i,(lo,hi) in enumerate(jitter) if classify(lo)!=classify(hi))
        questions.append(dict(q=q,centers=pts.tolist(),values=[round(v,3) for v in values],
                              states=states,answer=answer,uncertain=uncertain,unstable=unstable,
                              geometry_only_answer=previous,jitter=jitter,flags=[]))
    return questions,floor

