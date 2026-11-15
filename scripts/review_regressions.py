import json,os
from pathlib import Path
from dotenv import load_dotenv
from fablet.scene_director import SceneBlueprint, SceneScreenplay, review_script
from fablet.providers import EditorialProvider
from fablet.usage import UsageLog
load_dotenv()
for name in ('hut','tower'):
    root=Path('outputs')/(name+'_revised')
    editor=EditorialProvider(os.environ['OPENAI_MODEL']);editor.set_usage_log(UsageLog(root/'provider_usage.jsonl'))
    blueprint=SceneBlueprint.model_validate_json((root/'blueprint.json').read_text());screenplay=SceneScreenplay.model_validate_json((root/'screenplay.json').read_text())
    review,errors=review_script(blueprint,screenplay,editor)
    (root/'script_review.json').write_text(review.model_dump_json(indent=2))
    print(name,'review issues:',errors,flush=True)
