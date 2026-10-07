"""Freeze the visible resume document and its layout at submission time."""
from copy import deepcopy


SECTION_FIELDS = {
    'basic': ('name', 'phone', 'email', 'location', 'job_target', 'self_evaluation'),
    'education': ('school', 'major', 'date'),
    'experience': ('company', 'position', 'date', 'description'),
    'projects': ('name', 'role', 'date', 'description'),
    'campus_experience': ('organization', 'position', 'achievements'),
    'awards': ('name', 'rank', 'level'),
}
SECTIONS = (*SECTION_FIELDS, 'skills')


def as_dict(value):
    return value if isinstance(value, dict) else {}


def visible_resume_content(source):
    """Exclude hidden modules, individual fields, rows and skills from the payload."""
    source = as_dict(source)
    hidden = as_dict(source.get('hiddenSections'))
    hidden_basic = as_dict(as_dict(source.get('hiddenFields')).get('basic'))
    content = {
        'hiddenSections': {section: bool(hidden.get(section)) for section in SECTIONS},
        'hiddenFields': {'basic': {key: bool(hidden_basic.get(key)) for key in SECTION_FIELDS['basic']}},
        'layout': deepcopy(as_dict(source.get('layout'))),
    }
    for section, fields in SECTION_FIELDS.items():
        if hidden.get(section):
            continue
        if section == 'basic':
            basic = as_dict(source.get('basic'))
            content[section] = {key: deepcopy(basic[key]) for key in fields
                                if key in basic and not hidden_basic.get(key)}
            continue
        content[section] = []
        items = source.get(section) or []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get('_hidden'):
                continue
            hidden_fields = as_dict(item.get('_hiddenFields'))
            visible = {key: deepcopy(item[key]) for key in fields if key in item and not hidden_fields.get(key)}
            if any(str(value or '').strip() for value in visible.values()):
                content[section].append(visible)
    if not hidden.get('skills'):
        skills = source.get('skills') or []
        hidden_skills = as_dict(source.get('hiddenSkills'))
        content['skills'] = [deepcopy(skill) for skill in skills
                             if isinstance(skill, str) and skill.strip() and not hidden_skills.get(skill)] if isinstance(skills, list) else []
    return content


def snapshot_resume(resume):
    return {'title': resume.title, 'template_id': resume.template_id,
            'content': visible_resume_content(resume.content)}
