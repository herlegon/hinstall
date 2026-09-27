import json
from importlib.metadata import distributions

def get_pkg_info(d):
    try:
        if direct_url := d.read_text('direct_url.json'):
            info = json.loads(direct_url)
            if info.get('dir_info', {}).get('editable'):
                return {"version": d.version, "location": info.get('url', '').replace('file://', '')}
    except (FileNotFoundError, TypeError):
        pass
    return {"version": d.version}

print(json.dumps({d.name: get_pkg_info(d) for d in distributions()}))
