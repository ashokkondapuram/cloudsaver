"""Scan tracked release sources (not dependency/build caches); verify scanner catches a synthetic secret."""
from pathlib import Path
import json,subprocess,sys,tempfile
ROOT=Path(__file__).resolve().parents[1]


def main():
    scanner=sys.argv[1]
    with tempfile.TemporaryDirectory(prefix='cloudsaver-secrets-') as temporary:
        source=Path(temporary)/'source';source.mkdir()
        for name in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0'):
            if not name or name=='RELEASE_MANIFEST.json':continue
            origin=ROOT/name
            if not origin.is_file() or origin.is_symlink():continue
            target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(origin.read_bytes())
        report=Path(temporary)/'findings.json'
        result=subprocess.run([scanner,'dir',str(source),'--redact=100','--no-banner','--report-format','json','--report-path',str(report)],capture_output=True,text=True)
        if result.returncode:
            if report.exists():
                for finding in json.loads(report.read_text()):print('Secret candidate:',finding['File'],finding['StartLine'],finding['RuleID'])
            print('Secret scan failed. No secret values are printed.')
            return result.returncode
        fixture=Path(temporary)/'fixture';fixture.mkdir()
        # Construct at runtime so the detector self-test cannot become an actual
        # committed credential. This value is synthetic and never sent anywhere.
        (fixture/'example.env').write_text('GITHUB_TOKEN='+('ghp_'+'Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1Wx2')+'\n')
        check=subprocess.run([scanner,'dir',str(fixture),'--redact=100','--no-banner'],capture_output=True,text=True)
        if check.returncode!=1:raise RuntimeError('The secret scanner failed its negative control')
        print('Tracked release sources passed; synthetic-secret negative control was blocked.')
    return 0

if __name__=='__main__':raise SystemExit(main())
