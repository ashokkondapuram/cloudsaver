"""CONNECT-only TLS pass-through for exact approved identity endpoints; never decrypts or logs payloads."""
import ipaddress,os,re,select,socket,socketserver,threading,time


def approved_hosts(raw):
    hosts=frozenset(raw.split(','))
    if not hosts or len(hosts)>20 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?',h) or '..' in h for h in hosts):raise ValueError('Configure exact DNS hostnames without wildcards')
    for host in hosts:
        try:ipaddress.ip_address(host)
        except ValueError:continue
        raise ValueError('IP literals are not approved identity destinations')
    return hosts


def destination(authority,hosts):
    match=re.fullmatch(r'([a-z0-9.-]+):443',authority)
    if not match or match[1] not in hosts:raise ValueError('Destination is not approved')
    addresses={item[4][0] for item in socket.getaddrinfo(match[1],443,type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):raise ValueError('Identity destination must resolve only to public addresses')
    return sorted(addresses)


class Handler(socketserver.StreamRequestHandler):
    timeout=5
    def handle(self):
        remote=None
        try:
            first=self.rfile.readline(4097)
            if len(first)>4096:raise ValueError()
            parts=first.decode('ascii').strip().split(' ')
            if len(parts)!=3 or parts[0]!='CONNECT' or parts[2] not in ('HTTP/1.1','HTTP/1.0'):raise ValueError()
            total=len(first)
            while True:
                line=self.rfile.readline(4097);total+=len(line)
                if total>8192 or not line:raise ValueError()
                if line in (b'\r\n',b'\n'):break
            addresses=destination(parts[1],self.server.hosts)
            remote=socket.create_connection((addresses[0],443),timeout=5)
            self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n');self.wfile.flush()
            end=time.monotonic()+120;budget=8*1024*1024
            while budget>0 and time.monotonic()<end:
                ready,_,_=select.select([self.connection,remote],[],[],min(30,end-time.monotonic()))
                if not ready:break
                for stream in ready:
                    data=stream.recv(min(65536,budget))
                    if not data:return
                    budget-=len(data)
                    (remote if stream is self.connection else self.connection).sendall(data)
        except (ValueError,UnicodeError):
            self.wfile.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
        except (OSError,TimeoutError):
            pass
        finally:
            if remote:remote.close()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True;daemon_threads=True;request_queue_size=16
    slots=threading.BoundedSemaphore(16)
    def process_request(self,request,address):
        if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


def main():
    with Server(('0.0.0.0',3128),Handler) as server:
        server.hosts=approved_hosts(os.getenv('PLATFORM_IDENTITY_EGRESS_HOSTS','login.microsoftonline.com'))
        server.serve_forever()

if __name__=='__main__':main()
