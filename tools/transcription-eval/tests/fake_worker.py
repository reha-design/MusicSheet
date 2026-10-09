"""Real subprocess fixture. Does not load any model or acquire files."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

parser=argparse.ArgumentParser()
parser.add_argument('--mode',required=True);parser.add_argument('--seed');parser.add_argument('--output')
args=parser.parse_args()
if args.mode in {'hang','child'}:time.sleep(30);sys.exit(0)
if args.mode=='missing':sys.exit(0)
if args.mode in {'exit3','exit4'}:
    print('secret-sentinel exception/path',file=sys.stderr);sys.exit(int(args.mode[-1]))
if args.mode=='descendant':
    child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--mode','child'])
    Path('child.pid').write_text(str(child.pid))
shutil.copytree(args.seed,args.output)
if args.mode=='invalid':
    raw=Path(args.output)/'raw_transcription.json';wire=json.loads(raw.read_bytes())
    wire['note_events'][0]['pitch']=True;raw.write_text(json.dumps(wire))
if args.mode=='output_wait':time.sleep(30)
