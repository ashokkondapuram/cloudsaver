"""Review packages and a narrowly scoped GitHub App draft-PR adapter."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from urllib.parse import quote, urlsplit
from uuid import UUID, uuid5

import httpx


class GitOpsUnavailable(RuntimeError):
    pass


class GitOpsFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class GitOpsConfig:
    targets: tuple = ()
    enabled: bool = False
    app_id: str = ''

    @classmethod
    def load(cls):
        targets = json.loads(os.getenv('CLOUDSAVER_GITOPS_TARGETS','[]'))
        if not isinstance(targets,list) or len(targets)>100:
            raise ValueError('Configure at most 100 GitOps targets')
        seen = set()
        normalized = []
        for target in targets:
            if not isinstance(target,dict) or set(target) != {'target_id','tenant_id','repository','repository_id','base_branch','installation_id'}:
                raise ValueError('GitOps targets require explicit repository and installation bindings')
            row = dict(target,tenant_id=str(UUID(target['tenant_id'])))
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,39}',row['target_id']) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}/[A-Za-z0-9_.-]{1,100}',row['repository']):
                raise ValueError('Invalid GitOps target/repository name')
            if row['repository'].split('/')[1] in ('.','..'):
                raise ValueError('Invalid GitOps repository path')
            branch = row['base_branch']
            if not isinstance(branch,str) or not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_./-]{0,119}',branch) or any(x in branch for x in ('..','//','@{')) or branch.endswith(('/','.','.lock')):
                raise ValueError('Invalid GitOps base branch')
            if any(type(row[k]) is not int or not 1<=row[k]<2**53 for k in ('repository_id','installation_id')):
                raise ValueError('Numeric repository and installation IDs are required')
            key = row['tenant_id'],row['target_id']
            if key in seen:
                raise ValueError('Duplicate GitOps target')
            seen.add(key)
            normalized.append(row)
        app_id = os.getenv('CLOUDSAVER_GITHUB_APP_ID','')
        enabled = os.getenv('CLOUDSAVER_GITOPS_PUBLISH','false') == 'true'
        if enabled and (not app_id.isdigit() or not os.getenv('CLOUDSAVER_GITHUB_APP_PRIVATE_KEY')):
            raise ValueError('GitHub App configuration is required before enabling publishing')
        return cls(tuple(normalized),enabled,app_id)

    def target(self,tenant_id,target_id):
        target = next((t for t in self.targets if t['tenant_id']==tenant_id and t['target_id']==target_id),None)
        if target is None:
            raise ValueError('GitOps target is not configured for this workspace')
        return target


def build_review(scan, resource_ids, workspace, target):
    from app.remediation_terraform import generate_cloud_terraform_hcl
    if target['tenant_id'] != workspace['tenant_id']:
        raise ValueError('GitOps target belongs to another workspace')
    hcl = generate_cloud_terraform_hcl(scan, resource_ids, workspace)
    selected = [f for f in scan['findings'] if f['resource_id'] in resource_ids]
    identity = dict(scan_id=scan['scan_id'], resources=sorted(resource_ids),
                    repository=target['repository'],repository_id=target['repository_id'],base_branch=target['base_branch'],
                    terraform_sha256=hashlib.sha256(hcl.encode()).hexdigest())
    digest = hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    review_id = str(uuid5(UUID(workspace['tenant_id']),digest))
    directory = '.cloudsaver/reviews/' + review_id
    manifest = dict(schema_version='1',review_id=review_id,scan_id=scan['scan_id'],
                    scan_mode=scan['mode'],resource_ids=sorted(resource_ids),
                    terraform_sha256=hashlib.sha256(hcl.encode()).hexdigest(),
                    action='import_review_only', automatic_deletion=False)
    readme = ('# CloudSaver infrastructure review\n\n'
              f'Scan: `{scan["scan_id"]}`. Resources selected: {len(selected)}.\n\n'
              'This isolated directory contains import declarations only. It is not an active infrastructure module or deletion approval.\n\n'
              'Use a new local directory and read-only cloud credentials. Run `terraform init`, then '
              '`terraform plan -generate-config-out=reviewed-resources.tf -out=import-review.tfplan`. '
              'Review generated settings, state ownership, dependencies, backups and retention with the resource owner. '
              'Do not import resources already managed in another Terraform state.\n\n'
              'Exclude `.cloudsaver/reviews/` from automatic infrastructure discovery/apply workflows. Repository CI may run on this draft PR.\n\n'
              'No backup, snapshot or deletion was performed. Dollar savings are not verified. '
              'Any separate destructive change needs independent approval and recovery evidence.\n')
    body = (f'## CloudSaver import review\n\nScan `{scan["scan_id"]}`; {len(selected)} selected resource findings.\n\n'
            'This draft adds an isolated review package under `.cloudsaver/reviews/`. '
            'It changes no existing Terraform configuration and contains no deletion plan.\n\n'
            '- [ ] Confirm resource ownership and current associations.\n'
            '- [ ] Check existing state ownership, independent backups and retention.\n'
            '- [ ] Review an independently generated Terraform plan.\n'
            '- [ ] Obtain separate approval before any infrastructure mutation.\n\n'
            'CloudSaver has not executed remediation, verified backups or established realizable savings.\n\n'
            f'<!-- cloudsaver-review:{review_id} -->')
    files = {directory+'/imports.tf':hcl, directory+'/README.md':readme,
             directory+'/manifest.json':json.dumps(manifest,sort_keys=True,indent=2)+'\n'}
    fingerprint = hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    return dict(review_id=review_id,fingerprint=fingerprint,scan_id=scan['scan_id'],
                target_id=target['target_id'],repository=target['repository'],base_branch=target['base_branch'],
                branch='cloudsaver/review-'+review_id,title=f'[CloudSaver] Review {len(selected)} cloud resources',
                body=body,files=files,draft=True)


class GitHubApp:
    def __init__(self,app_id,*,private_key=None,transport=None):
        self.app_id = app_id
        self.private_key = private_key
        self.transport = transport

    def publish(self,target,package):
        try:
            return self._publish(target,package)
        except (GitOpsFailure,GitOpsUnavailable):
            raise
        except Exception:
            raise GitOpsFailure('GitHub returned an unsupported review response') from None

    def _publish(self,target,package):
        import jwt
        key = self.private_key or os.getenv('CLOUDSAVER_GITHUB_APP_PRIVATE_KEY')
        if not key or not self.app_id:
            raise GitOpsUnavailable('GitHub App is not configured')
        now = int(time.time())
        try:
            app_token = jwt.encode(dict(iat=now-60,exp=now+540,iss=self.app_id),key,algorithm='RS256')
        except Exception:
            raise GitOpsUnavailable('GitHub App credential is unavailable') from None
        with httpx.Client(base_url='https://api.github.com',timeout=httpx.Timeout(30,connect=5),
                          follow_redirects=False,transport=self.transport) as client:
            def request(method,path,token,*,body=None,allowed=(200,201)):
                try:
                    with client.stream(method,path,headers={'Authorization':'Bearer '+token,
                          'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'},json=body) as response:
                        raw = bytearray()
                        for chunk in response.iter_bytes():
                            raw.extend(chunk)
                            if len(raw)>2_000_000:
                                raise GitOpsFailure('GitHub response exceeded the limit')
                        if response.status_code not in allowed:
                            raise GitOpsFailure('GitHub rejected the review operation')
                        return response.status_code, json.loads(raw) if raw else None
                except (httpx.HTTPError,ValueError,TypeError):
                    raise GitOpsFailure('GitHub review result is uncertain; retry the same request key') from None
            _,access = request('POST',f'/app/installations/{target["installation_id"]}/access_tokens',app_token,
                body={'repository_ids':[target['repository_id']], 'permissions':{'contents':'write','pull_requests':'write'}})
            if not isinstance(access,dict) or not isinstance(access.get('token'),str) or not access['token']:
                raise GitOpsFailure('GitHub returned an invalid installation credential')
            try:
                expires = datetime.fromisoformat(access['expires_at'].replace('Z','+00:00'))
                if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
                    raise ValueError()
            except (ValueError,KeyError,TypeError):
                raise GitOpsFailure('GitHub installation credential has invalid expiry') from None
            token, repo = access['token'], '/repos/'+target['repository']
            _,metadata = request('GET',repo,token)
            if metadata.get('id') != target['repository_id'] or metadata.get('full_name','').lower() != target['repository'].lower() or metadata.get('archived') is not False:
                raise GitOpsFailure('GitHub repository identity does not match the configured target')
            branch = package['branch']
            def pull_result(item,require_draft=False):
                number = item.get('number')
                expected = f'https://github.com/{target["repository"]}/pull/{number}'
                if (type(number) is not int or number<=0 or item.get('html_url') != expected
                        or item.get('head',{}).get('ref') != branch
                        or item.get('head',{}).get('repo',{}).get('id') != target['repository_id']
                        or item.get('base',{}).get('ref') != target['base_branch']
                        or item.get('base',{}).get('repo',{}).get('id') != target['repository_id']
                        or item.get('state') not in ('open','closed') or type(item.get('draft')) is not bool
                        or (require_draft and item['draft'] is not True)
                        or f'<!-- cloudsaver-review:{package["review_id"]} -->' not in item.get('body','')):
                    raise GitOpsFailure('GitHub returned an inconsistent pull request')
                head_sha = item.get('head',{}).get('sha')
                if not isinstance(head_sha,str) or not re.fullmatch('[0-9a-f]{40}',head_sha):
                    raise GitOpsFailure('GitHub returned an invalid PR revision')
                for path,content in package['files'].items():
                    _,blob = request('GET',repo+'/contents/'+quote(path,safe='/')+'?ref='+head_sha,token)
                    raw = content.encode()
                    expected_blob = hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
                    if blob.get('type') != 'file' or blob.get('sha') != expected_blob:
                        raise GitOpsFailure('Existing PR review files differ from the preview; manual review is required')
                return dict(pr_url=expected,pr_number=number,state=item.get('state'),draft=item.get('draft',False))
            def existing_pull():
                head = target['repository'].split('/')[0]+':'+branch
                _,items = request('GET',repo+'/pulls?state=all&per_page=100&head='+quote(head,safe='')+'&base='+quote(target['base_branch'],safe=''),token)
                if not isinstance(items,list) or len(items)>=100 or len(items)>1:
                    raise GitOpsFailure('GitHub pull request history is ambiguous')
                return pull_result(items[0]) if items else None
            previous = existing_pull()
            if previous:
                return previous
            _,base = request('GET',repo+'/git/ref/heads/'+quote(target['base_branch'],safe=''),token)
            base_sha = base.get('object',{}).get('sha')
            if not isinstance(base_sha,str) or not re.fullmatch('[0-9a-f]{40}',base_sha):
                raise GitOpsFailure('GitHub returned an invalid base revision')
            _,base_commit = request('GET',repo+'/git/commits/'+base_sha,token)
            tree_sha = base_commit.get('tree',{}).get('sha')
            if not isinstance(tree_sha,str) or not re.fullmatch('[0-9a-f]{40}',tree_sha):
                raise GitOpsFailure('GitHub returned an invalid base tree')
            _,tree = request('POST',repo+'/git/trees',token,body={'base_tree':tree_sha,'tree':[
                dict(path=path,mode='100644',type='blob',content=content) for path,content in sorted(package['files'].items())]})
            new_tree = tree.get('sha')
            if not isinstance(new_tree,str) or not re.fullmatch('[0-9a-f]{40}',new_tree):
                raise GitOpsFailure('GitHub returned an invalid review tree')
            _,commit = request('POST',repo+'/git/commits',token,body={'message':package['title'], 'tree':new_tree,'parents':[base_sha]})
            commit_sha = commit.get('sha')
            if not isinstance(commit_sha,str) or not re.fullmatch('[0-9a-f]{40}',commit_sha):
                raise GitOpsFailure('GitHub returned an invalid review commit')
            status,_ = request('POST',repo+'/git/refs',token,body={'ref':'refs/heads/'+branch,'sha':commit_sha},allowed=(201,422))
            if status == 422:
                # Never force-update a branch. A timed-out prior attempt may already own it.
                _,ref = request('GET',repo+'/git/ref/heads/'+quote(branch,safe=''),token)
                _,prior_commit = request('GET',repo+'/git/commits/'+str(ref.get('object',{}).get('sha')),token)
                if prior_commit.get('tree',{}).get('sha') != new_tree:
                    raise GitOpsFailure('Review branch already exists with different content; manual review is required')
            previous = existing_pull()
            if previous:
                return previous
            _,created = request('POST',repo+'/pulls',token,body={'title':package['title'],'body':package['body'],
                'head':branch,'base':target['base_branch'],'draft':True,'maintainer_can_modify':False})
            return pull_result(created,require_draft=True)
