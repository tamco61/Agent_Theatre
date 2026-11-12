"""Экспортировать публичную партию в автономный HTML со столом и моделями."""
import argparse
import json
from pathlib import Path
from app.mafia.replay import table_html


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path,nargs='?',default=Path('results'))
    args=parser.parse_args()
    public=json.loads((args.directory/'public.json').read_text())
    source=args.directory/'provenance.json'
    provenance=json.loads(source.read_text()) if source.exists() else {}
    target=args.directory/'table.html'
    target.write_text(table_html(public,provenance))
    project = Path(__file__).resolve().parents[1]
    if args.directory.resolve() == project/'results':
        (project/'Mafia_Table.html').write_text(target.read_text())
    print(target.resolve())


if __name__=='__main__':main()
