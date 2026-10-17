"""Validate canonical skill metadata and local reference targets, not skill quality."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def validate(root=ROOT):
    results=[]
    for skill in sorted((root/'skills').glob('*/SKILL.md')):
        text=skill.read_text(encoding='utf-8')
        assert text.startswith('---\n') and '\n---\n' in text
        front=text.split('---',2)[1]
        assert f'name: {skill.parent.name}' in front
        assert re.search(r'^description: .+',front,re.M)
        assert len(text.split()) >= 180,'Skill lacks substantive instructions'
        links=[]
        for target in re.findall(r'\]\(([^)]+)\)',text):
            if '://' in target: continue
            path=(skill.parent/target.split('#')[0]).resolve()
            assert path.is_relative_to(root.resolve()) and path.exists(),(skill,target)
            links.append(target)
        results.append({'name':skill.parent.name,'words':len(text.split()),'references':links})
    assert len(results)==5
    return {'status':'VERIFIED metadata and reference integrity; expert depth judged independently',
            'skills':results}

if __name__=='__main__': print(json.dumps(validate(),indent=2))
