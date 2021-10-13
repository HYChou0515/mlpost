import json
import sys
import os
import tempfile

md = sys.argv[1]

if os.environ.get('devtoapi', None) is None:
	print('devtoapi not defined')
	exit -1
devtoapi = os.environ.get('devtoapi')

with open(md, 'r') as f:
	meta_start = False
	meta = {}
	for i, _line in enumerate(f):
		line = _line.strip()
		if not meta_start and line == '---':
			meta_start = True
			continue
		if meta_start:
			if line == '---':
				meta_start = False
				break
			k, _, v = line.partition(':')
			k = k.strip()
			v = v.strip()
			meta[k] = v
	t2name = None
	with tempfile.NamedTemporaryFile('w', delete=False) as t2:
		t2name = t2.name
	with tempfile.NamedTemporaryFile('w') as t:
		t.write(f.read())
		t.flush()
		os.system(f'cat {t.name} | jq "." --raw-input --slurp > {t2name}')
	with open(t2name, 'r') as t2:
		meta['body_markdown'] = t2.read().strip()
article = {"article": meta}
with tempfile.NamedTemporaryFile('w') as t:
	t.write(json.dumps(article))
	t.flush()
	os.system(f'''echo curl -X POST -H "Content-Type: application/json" \
	    -H "api-key: {devtoapi}" \
	    -d @{t.name} \
	    https://dev.to/api/articles''')
	os.system(f'''curl -X POST -H "Content-Type: application/json" \
	    -H "api-key: {devtoapi}" \
	    -d @{t.name} \
	    https://dev.to/api/articles''')
os.remove(t2name)
