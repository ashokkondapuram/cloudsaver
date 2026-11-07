/** Local-volume session persistence. Share the volume only on a single host;
 * multi-host deployments must use a distributed session adapter. */
import {DatabaseSync} from 'node:sqlite';
import {createCipheriv, createDecipheriv, createHash, randomBytes} from 'node:crypto';
import {mkdirSync, chmodSync} from 'node:fs';
import {dirname} from 'node:path';

export class SessionStore {
  private db: DatabaseSync;
  private key: Buffer;
  constructor(path: string, secret: string) {
    if (secret.length < 32) throw new Error('Session encryption secret is unavailable');
    if (path !== ':memory:') mkdirSync(dirname(path), {recursive:true, mode:0o700});
    this.db = new DatabaseSync(path);
    if (path !== ':memory:') chmodSync(path, 0o600);
    this.key = createHash('sha256').update('cloudsaver-portal-session-v1\0' + secret).digest();
    this.db.exec('PRAGMA busy_timeout=3000; PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, payload TEXT NOT NULL, expires INTEGER NOT NULL, idle INTEGER NOT NULL, refresh_until INTEGER NOT NULL DEFAULT 0, refresh_fence INTEGER NOT NULL DEFAULT 0);');
  }
  private encode(id: string, value: unknown) {
    const iv=randomBytes(12), cipher=createCipheriv('aes-256-gcm',this.key,iv);
    cipher.setAAD(Buffer.from(id));
    const body=Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()]);
    return Buffer.concat([iv,cipher.getAuthTag(),body]).toString('base64');
  }
  create(id: string, value: unknown, expires: number, idle: number) {
    this.db.prepare('DELETE FROM sessions WHERE expires<=? OR idle<=?').run(Date.now(),Date.now());
    this.db.prepare('INSERT INTO sessions(id,payload,expires,idle) VALUES(?,?,?,?)').run(id,this.encode(id,value),expires,idle);
  }
  read<T>(id: string, now: number, touch: boolean, idleMs: number): T|null {
    const row=this.db.prepare('SELECT payload FROM sessions WHERE id=? AND expires>? AND idle>?').get(id,now,now);
    if (!row) return null;
    try {
      const raw=Buffer.from(String(row.payload),'base64'), decipher=createDecipheriv('aes-256-gcm',this.key,raw.subarray(0,12));
      decipher.setAAD(Buffer.from(id));decipher.setAuthTag(raw.subarray(12,28));
      const value=JSON.parse(Buffer.concat([decipher.update(raw.subarray(28)),decipher.final()]).toString('utf8')) as T;
      if(touch)this.db.prepare('UPDATE sessions SET idle=MIN(expires,?) WHERE id=? AND expires>? AND idle>?').run(now+idleMs,id,now,now);
      return value;
    } catch {this.delete(id);return null;}
  }
  take<T>(id: string, now: number): T|null {
    this.db.exec('BEGIN IMMEDIATE');
    try {const value=this.read<T>(id,now,false,0);this.delete(id);this.db.exec('COMMIT');return value;}
    catch(error){this.db.exec('ROLLBACK');throw error;}
  }
  delete(id: string) {this.db.prepare('DELETE FROM sessions WHERE id=?').run(id);}
  claimRefresh(id: string, now: number) {
    const until=now+30_000;
    const row=this.db.prepare('UPDATE sessions SET refresh_until=?,refresh_fence=refresh_fence+1 WHERE id=? AND refresh_until<=? AND expires>? AND idle>? RETURNING refresh_fence').get(until,id,now,now,now);
    return row ? Number(row.refresh_fence) : null;
  }
  finishRefresh(id: string, fence: number, value: unknown, now: number) {
    return !!this.db.prepare('UPDATE sessions SET payload=?,refresh_until=0 WHERE id=? AND refresh_fence=? AND refresh_until>? AND expires>? AND idle>?').run(this.encode(id,value),id,fence,now,now,now).changes;
  }
  ping(){this.db.prepare('SELECT 1').get();}
  close(){this.db.close();}
}
