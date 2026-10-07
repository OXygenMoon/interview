"""Explainable rankings based on a student's latest completed interview per job."""
import math

from ..models import InterviewSession


def score_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) and 0 <= value <= 100 else None


def recommend_students(query):
    records = query.filter(InterviewSession.status == 'completed').order_by(
        InterviewSession.start_time.desc(), InterviewSession.id.desc()).all()
    seen, candidates = set(), []
    for record in records:
        if record.user_id in seen:
            continue
        seen.add(record.user_id)
        if not record.user.active or record.evaluation_source not in {None, 'ai'}:
            continue
        total = score_value(record.total_score)
        skills = score_value((record.radar_data or {}).get('专业技能')) if isinstance(record.radar_data, dict) else None
        if total is None or skills is None or skills < 60:
            continue
        match = round(skills * .6 + total * .4, 1)
        if match < 75:
            continue
        candidates.append({'record': record, 'match': match, 'skills': skills, 'total': total})
    return sorted(candidates, key=lambda candidate: (
        candidate['match'], candidate['total'], candidate['record'].id), reverse=True)
