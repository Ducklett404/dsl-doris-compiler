"""Archive current self-test results without JVM properties or credential-bearing environment."""
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args()
    folder=args.folder.resolve();folder.mkdir(parents=True,exist_ok=True)
    if (folder/'junit-results.json').exists(): raise ValueError('Preserve prior archive')
    aggregate={}
    for label,directory in [('main',ROOT/'target/surefire-reports'),('executor',ROOT/'executor-doris/target/surefire-reports')]:
        totals=dict(tests=0,failures=0,errors=0,skipped=0);suites=[]
        for path in sorted(directory.glob('TEST-*.xml')):
            root=ET.parse(path).getroot()
            summary=dict(name=root.attrib['name'],**{key:int(root.attrib[key]) for key in totals})
            summary['cases']=[dict(name=c.attrib['name'],className=c.attrib.get('classname'),time=c.attrib.get('time'),
                status='FAIL' if c.find('failure') is not None or c.find('error') is not None else 'SKIPPED' if c.find('skipped') is not None else 'PASS') for c in root.findall('testcase')]
            suites.append(summary)
            for key in totals: totals[key]+=summary[key]
        aggregate[label]=dict(**totals,suites=suites)
    (folder/'junit-results.json').write_text(json.dumps(aggregate,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for source in ['reports/automation/latest.json','reports/automation/latest.md','reports/compiler-performance/latest.json','reports/compiler-performance/latest.md',
                   'reports/scope/phase1-scope-validation.json','reports/scope/phase1-scope-validation.md']:
        path=ROOT/source;destination=folder/path.parent.name/path.name
        destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    automation=json.loads((ROOT/'reports/automation/latest.json').read_text(encoding='utf-8-sig'))
    for name in ['project-window-boundaries','project-rsi-tail-boundaries','project-availability-explanations','project-field-boundaries']:
        check=automation['checks'].get(name,{})
        if 'outputPath' not in check:continue
        path=Path(check['outputPath']).resolve()
        if path.parent!=ROOT/'target' or not path.name.startswith('project-'):raise ValueError('Unexpected boundary artifact path')
        destination=folder/'portable-boundaries'/(name+'.json');destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
    print(json.dumps({key:{field:data[field] for field in ['tests','failures','errors','skipped']} for key,data in aggregate.items()}))


if __name__=='__main__': main()
