"""Only explicitly registered review routes may reach the core service."""
from uuid import UUID
from fastapi import Depends, Header, Query, Request
from app.gitops_api import bounded_json
from services.common import upstream


def register(app, allowed, targets, transport):
    async def send(request,path,authorization,params=None):
        return await upstream(request.method,targets['scanner'],path,authorization,params=params,
                              json=await bounded_json(request) if request.method!='GET' else None,
                              transport=transport,preserve_response=True,
                              command_headers={k:request.headers.get(k) for k in ('Idempotency-Key','If-Match')})

    @app.get('/api/v1/engineering/capabilities')
    async def capabilities(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,'/api/v1/engineering/capabilities',authorization)

    @app.get('/api/v1/engineering/workloads')
    async def workloads(request:Request,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),row=Depends(allowed),authorization:str=Header()):
        return await send(request,'/api/v1/engineering/workloads',authorization,dict(limit=limit,**({'cursor':cursor} if cursor else {})))

    @app.post('/api/v1/engineering/workloads',status_code=201)
    async def create(request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,'/api/v1/engineering/workloads',authorization)

    @app.get('/api/v1/engineering/workloads/{workload_id}')
    @app.patch('/api/v1/engineering/workloads/{workload_id}')
    async def detail(workload_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}',authorization)

    @app.get('/api/v1/engineering/workloads/{workload_id}/members')
    async def members(workload_id:UUID,request:Request,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/members',authorization,dict(limit=limit,**({'cursor':cursor} if cursor else {})))

    @app.post('/api/v1/engineering/workloads/{workload_id}/members',status_code=201)
    async def member(workload_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/members',authorization)

    @app.get('/api/v1/engineering/workloads/{workload_id}/plans')
    async def plans(workload_id:UUID,request:Request,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/plans',authorization,dict(limit=limit,**({'cursor':cursor} if cursor else {})))

    @app.post('/api/v1/engineering/workloads/{workload_id}/plans',status_code=201)
    async def plan(workload_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/plans',authorization)

    @app.get('/api/v1/engineering/plans/{plan_id}/versions')
    async def versions(plan_id:UUID,request:Request,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/plans/{plan_id}/versions',authorization,dict(limit=limit,**({'cursor':cursor} if cursor else {})))

    @app.post('/api/v1/engineering/workloads/{workload_id}/plans/{plan_id}/versions',status_code=201)
    async def revision(workload_id:UUID,plan_id:UUID,request:Request,row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/plans/{plan_id}/versions',authorization)

    @app.get('/api/v1/engineering/workloads/{workload_id}/events')
    async def events(workload_id:UUID,request:Request,limit:int=Query(50,ge=1,le=200),cursor:str|None=Query(None,max_length=1000),row=Depends(allowed),authorization:str=Header()):
        return await send(request,f'/api/v1/engineering/workloads/{workload_id}/events',authorization,dict(limit=limit,**({'cursor':cursor} if cursor else {})))
