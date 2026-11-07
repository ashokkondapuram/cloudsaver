/** Shared encrypted portal sessions with server-time TTLs and atomic fencing. */
import {createClient} from 'redis';
import {createCipheriv,createDecipheriv,createHash,randomBytes} from 'node:crypto';

type Command = (args:string[])=>Promise<unknown>;
const NOW="local t=redis.call('TIME');local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000);";
const VALID="if redis.call('EXISTS',KEYS[1])==0 then return nil end;local expires=tonumber(redis.call('HGET',KEYS[1],'expires'));local idle=tonumber(redis.call('HGET',KEYS[1],'idle'));if expires<=now or idle<=now then redis.call('DEL',KEYS[1]);return nil end;";
const TTL="redis.call('PEXPIREAT',KEYS[1],math.min(expires,idle));";
export const SESSION_SCRIPTS={
 create:NOW+"if redis.call('EXISTS',KEYS[1])==1 then return 0 end;local expires=tonumber(ARGV[2]);local idle=tonumber(ARGV[3]);if expires<=now or idle<=now then return 0 end;redis.call('HSET',KEYS[1],'payload',ARGV[1],'expires',expires,'idle',idle,'fence',0,'lease',0);"+TTL+"return 1;",
 read:NOW+VALID+"local payload=redis.call('HGET',KEYS[1],'payload');if ARGV[1]=='1' then idle=math.min(expires,now+tonumber(ARGV[2]));redis.call('HSET',KEYS[1],'idle',idle);"+TTL+"end;return payload;",
 take:NOW+VALID+"local payload=redis.call('HGET',KEYS[1],'payload');redis.call('DEL',KEYS[1]);return payload;",
 claim:NOW+VALID+"if tonumber(redis.call('HGET',KEYS[1],'lease'))>now then return nil end;redis.call('HSET',KEYS[1],'lease',now+30000);return redis.call('HINCRBY',KEYS[1],'fence',1);",
 finish:NOW+VALID+"if tonumber(redis.call('HGET',KEYS[1],'fence'))~=tonumber(ARGV[1]) or tonumber(redis.call('HGET',KEYS[1],'lease'))<=now then return 0 end;redis.call('HSET',KEYS[1],'payload',ARGV[2],'lease',0);return 1;",
};
export class RedisSessionStore {
 private key:Buffer;
 private command:Command;
 private disconnect:()=>void;
 constructor(command:Command,secret:string,disconnect=()=>{}) {
  if(secret.length<32)throw new Error('Session encryption secret is unavailable');
  this.command=command;this.disconnect=disconnect;
  this.key=createHash('sha256').update('cloudsaver-portal-session-v1\0'+secret).digest();
 }
 static async connect(url:string,secret:string) {
  if(secret.length<32)throw new Error('Session encryption secret is unavailable');
  const client=createClient({url,disableOfflineQueue:true,socket:{connectTimeout:3000,reconnectStrategy:retries=>Math.min(3000,100*2**Math.min(retries,5))}});
  client.on('error',()=>{}); // Public callers get a safe unavailable error, never a Redis URL.
  let deadline:ReturnType<typeof setTimeout>|undefined;
  try {await Promise.race([client.connect(),new Promise((_,reject)=>{deadline=setTimeout(()=>reject(new Error('Session store unavailable')),4000);})]);}
  catch {if(client.isOpen)client.destroy();throw new Error('Session store unavailable');}
  finally {clearTimeout(deadline);}
  return new RedisSessionStore(args=>client.sendCommand(args,{abortSignal:AbortSignal.timeout(3000)}),secret,()=>{if(client.isOpen)client.destroy();});
 }
 private name(id:string){return 'cloudsaver:portal:session:v1:'+createHash('sha256').update(id).digest('hex');}
 private encode(id:string,value:unknown){const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',this.key,iv);cipher.setAAD(Buffer.from(id));const body=Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()]);return Buffer.concat([iv,cipher.getAuthTag(),body]).toString('base64');}
 private decode<T>(id:string,payload:unknown):T|null {
  if(payload===null||payload===undefined)return null;
  const raw=Buffer.from(String(payload),'base64'),cipher=createDecipheriv('aes-256-gcm',this.key,raw.subarray(0,12));cipher.setAAD(Buffer.from(id));cipher.setAuthTag(raw.subarray(12,28));return JSON.parse(Buffer.concat([cipher.update(raw.subarray(28)),cipher.final()]).toString('utf8')) as T;
 }
 private eval(script:string,id:string,args:string[]=[]){return this.command(['EVAL',script,'1',this.name(id),...args]);}
 async create(id:string,value:unknown,expires:number,idle:number){if(await this.eval(SESSION_SCRIPTS.create,id,[this.encode(id,value),String(expires),String(idle)])!==1)throw new Error('Session could not be created');}
 async read<T>(id:string,_now:number,touch:boolean,idleMs:number):Promise<T|null>{const payload=await this.eval(SESSION_SCRIPTS.read,id,[touch?'1':'0',String(idleMs)]);try{return this.decode<T>(id,payload);}catch{return null;}}
 async take<T>(id:string,_now:number):Promise<T|null>{const payload=await this.eval(SESSION_SCRIPTS.take,id);try{return this.decode<T>(id,payload);}catch{return null;}}
 async delete(id:string){await this.command(['DEL',this.name(id)]);}
 async claimRefresh(id:string,_now:number):Promise<number|null>{const value=await this.eval(SESSION_SCRIPTS.claim,id);return typeof value==='number'?value:null;}
 async finishRefresh(id:string,fence:number,value:unknown,_now:number){return await this.eval(SESSION_SCRIPTS.finish,id,[String(fence),this.encode(id,value)])===1;}
 async ping(){if(await this.command(['PING'])!=='PONG')throw new Error('Session store unavailable');}
 close(){this.disconnect();}
}
