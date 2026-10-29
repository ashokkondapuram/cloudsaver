'use client';
import {useEffect,useState} from 'react';
import {portal,errorMessage} from '../../lib/api';
import type {Workspace} from '../../lib/types';
import {useSession} from '../SessionProvider';
import {Dialog} from '../ui/Dialog';
import {Notice} from '../ui/shared';
import {AccessFields,accessBody,accessError,defaultAccess,expiryError,ExpiryField,expiryIso,expiryLimits,SecretReveal} from './KeyFields';

type IssuedLicense={token:string;license_id:string;expires_at:string;roles:string[];providers:string[]};
export function LicenseTokenDialog({open,workspace,onClose}:{open:boolean;workspace:Workspace;onClose:()=>void}){
  const {session}=useSession();
  const [name,setName]=useState('');
  const [access,setAccess]=useState(()=>defaultAccess(workspace));
  const [expiry,setExpiry]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [issued,setIssued]=useState<IssuedLicense|null>(null);
  useEffect(()=>{if(open){setName('');setAccess(defaultAccess(workspace));setExpiry(expiryLimits().fallback);setError('');setIssued(null);}},[open]);
  function close(){setIssued(null);onClose();}
  async function submit(event:React.FormEvent){
    event.preventDefault();
    const invalid=accessError(access,session)||expiryError(expiry);
    if(!name.trim()||invalid){setError(invalid||'Enter a license name.');return;}
    setBusy(true);setError('');
    try{setIssued(await portal<IssuedLicense>(`workspaces/${encodeURIComponent(workspace.tenant_id)}/license-tokens`,{method:'POST',body:{name:name.trim(),...accessBody(access,session),expires_at:expiryIso(expiry)}}));}
    catch(cause){setError(errorMessage(cause));}finally{setBusy(false);}
  }
  return <Dialog open={open} onClose={close} title={issued?'Your license token':'Issue offline license token'} dismissible={!issued&&!busy}>
    {issued?<><div className="dialog-content"><Notice tone="warning">Valid until {new Date(issued.expires_at).toLocaleString()}. CloudSaver verifies this token locally. Platform key revocation, role changes and suspension do not invalidate it; use the CloudSaver local denylist for earlier revocation.</Notice><p>License ID: <code>{issued.license_id}</code></p><p>Roles: {issued.roles.join(', ')} · Providers: {issued.providers.join(', ')||'None'}</p></div><SecretReveal secret={issued.token} label="New license token" onClose={close}/></>:<form className="dialog-form" onSubmit={submit}>
      <div className="dialog-content">
        <Notice tone="warning">This bearer token contains a signed snapshot of current access and plan limits. Anyone holding it can use that access until expiry. It does not require a running platform or Keycloak. Choose the shortest practical expiry; it may be capped to the paid billing period.</Notice>
        {error&&<Notice tone="error">{error}</Notice>}
        <label className="field">License name<input value={name} maxLength={80} required onChange={event=>setName(event.target.value)}/></label>
        <AccessFields access={access} onChange={setAccess} workspace={workspace} session={session} showErrors={false} freezeProviders/>
        <ExpiryField value={expiry} onChange={setExpiry} showErrors={false}/>
      </div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={close} disabled={busy}>Cancel</button><button type="submit" className="button primary" disabled={busy}>{busy?'Issuing…':'Issue license token'}</button></div>
    </form>}
  </Dialog>;
}
