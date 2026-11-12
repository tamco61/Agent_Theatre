"""Обновить встроенные исходники, сохранив настройки ячеек и отчёт."""
import argparse
import base64
import io
import json
from pathlib import Path
import re
import zipfile
from app.mafia.replay import table_html

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--keep-replay',action='store_true',help='Не пересоздавать HTML старой партии')
    args=parser.parse_args()
    record=ROOT/'results'
    public=json.loads((record/'public.json').read_text())
    provenance=json.loads((record/'provenance.json').read_text())
    html=table_html(public,provenance)
    if not args.keep_replay:
        (record/'table.html').write_text(html)
        (ROOT/'Mafia_Table.html').write_text(html)
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in (ROOT/'app').rglob('*'):
            if path.is_file() and path.suffix in ('.py','.txt','.html'):
                text=path.read_text().replace('from app.','from mafia_lab.').replace('import app.','import mafia_lab.')
                archive.writestr('mafia_lab/'+path.relative_to(ROOT/'app').as_posix(),text)
        for name in ('public.json','public.md','summary.json','provenance.json','chat.html','table.html'):
            archive.writestr('results/'+name,(record/name).read_bytes())
        archive.writestr('chat-template.html',(ROOT/'assets/chat.html').read_bytes())
    blob=base64.b64encode(buffer.getvalue()).decode()
    for name in ('LLM_Theatre.ipynb','Mafia_Kaggle_Live.ipynb'):
        path=ROOT/name
        notebook=json.loads(path.read_text()); replaced=0
        for cell in notebook['cells']:
            if cell['cell_type']=='code':
                source,count=re.subn(r'PACKAGE = "[A-Za-z0-9+/=]+"',lambda m:'PACKAGE = "'+blob+'"',''.join(cell['source']))
                replaced+=count
                compile(source,name,'exec')
                cell['source']=source.splitlines(keepends=True)
        if replaced!=1:raise ValueError('Ожидается одна ячейка пакета: '+name)
        path.write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n')
    print('Обновлены два ноутбука; старый HTML сохранён.' if args.keep_replay else
          'Обновлены HTML и два ноутбука; отчёт и настройки ячеек сохранены.')


if __name__=='__main__':main()
