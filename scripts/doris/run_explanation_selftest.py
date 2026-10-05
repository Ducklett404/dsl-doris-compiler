"""Archive a complete self-test run while preserving earlier tracked portable evidence."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from validate_project_sources import ROOT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--report-dir',type=Path,required=True);args=parser.parse_args()
    folder=args.report_dir.resolve()
    if folder.exists():raise ValueError('Use a fresh report directory')
    folder.mkdir(parents=True)
    old=[ROOT/'reports/history-features/2026-10-04/portable-historical-boundaries.json',ROOT/'reports/official-route/2026-10-04/portable-rolling-boundaries.json']
    originals={path:path.read_bytes() for path in old}
    try:
        with (folder/'runner.log').open('wb') as output:
            subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/doris/run_wsl_integration.py'),'--report-dir',str(folder)],stdout=output,stderr=subprocess.STDOUT,check=True,cwd=ROOT)
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/doris/archive_project_selftest.py'),str(folder)],check=True,cwd=ROOT)
        for path in old:
            destination=folder/'portable-boundaries'/path.name;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    finally:
        for path,data in originals.items():path.write_bytes(data)


if __name__=='__main__':main()
