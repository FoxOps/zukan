import urllib.request, urllib.error, json, getpass, secrets, time, csv, io
from pathlib import Path

BASE='http://localhost:8000'
results=[]
def req(method,path,body=None,token=None,headers=None,raw=None):
    h=dict(headers or {})
    if token: h['Authorization']='Bearer '+token
    if body is not None:
        raw=json.dumps(body).encode(); h['Content-Type']='application/json'
    r=urllib.request.Request(BASE+path,data=raw,headers=h,method=method)
    try: response=urllib.request.urlopen(r,timeout=30)
    except urllib.error.HTTPError as e: response=e
    data=response.read().decode(errors='replace')
    try: data=json.loads(data)
    except ValueError: pass
    return response.status,data,{k.lower():v for k,v in response.headers.items()}
def record(name,response,detail=None):
    status,data,headers=response
    item={'test':name,'status':status}
    if detail is not None: item['detail']=detail
    elif isinstance(data,dict): item['detail']={k:v for k,v in data.items() if k not in ('access_token','refresh_token')}
    results.append(item); print(json.dumps(item,ensure_ascii=False),flush=True)
def login(name,password):
    r=req('POST','/api/auth/login',{'username':name,'password':password})
    if r[0]!=200: raise RuntimeError('Login failed: '+name+' '+str(r[0]))
    return r[1]
userpw=getpass.getpass('codex_user password: ')
adminpw=getpass.getpass('codex_admin password: ')
u=login('codex_user',userpw); a=login('codex_admin',adminpw)
ut=u['access_token']; at=a['access_token']
uid=None; owned=None; rt=None
try:
    record('health',req('GET','/api/health'))
    for path in ['/','/login','/api/auth/providers']:
        r=req('GET',path); record('headers '+path,r,{'headers':r[2]})
    for path in ['/api/auth/me','/api/users','/api/admin/overview','/api/collection','/api/games']:
        record('anonymous '+path,req('GET',path))
    for path in ['/api/users','/api/admin/overview','/api/admin/import-folders']:
        record('user forbidden '+path,req('GET',path,token=ut))
    record('user me',req('GET','/api/auth/me',token=ut))
    r=req('GET','/api/users',token=at); record('admin users',r,{'count':len(r[1]) if isinstance(r[1],list) else None})
    name='audit_tmp_'+secrets.token_hex(5); pw=secrets.token_urlsafe(32); newpw=secrets.token_urlsafe(32)
    r=req('POST','/api/users',{'username':name,'password':pw},at); record('create temporary account',r)
    assert r[0]==201; uid=r[1]['id']
    t=login(name,pw); rt=t['refresh_token']; tt=t['access_token']
    r=req('POST','/api/auth/login',{'username':name,'password':pw,'mode':'cookie'},headers={'X-TCG-CSRF':'1'})
    cookie='tcg_access='+tt
    record('cookie login flags',r,{'refresh_cookie_attributes':r[2].get('set-cookie','').split(';')[1:]})
    record('CSRF missing',req('PATCH','/api/auth/me',{'language':'fr'},headers={'Cookie':cookie}))
    record('CSRF valid',req('PATCH','/api/auth/me',{'language':'fr'},headers={'Cookie':cookie,'X-TCG-CSRF':'1'}))
    record('cross-origin preflight',req('OPTIONS','/api/auth/me',headers={'Origin':'https://audit.invalid','Access-Control-Request-Method':'PATCH','Access-Control-Request-Headers':'X-TCG-CSRF,content-type'}))
    record('mass assignment role',req('PATCH','/api/auth/me',{'role':'admin'},tt))
    record('role after mass assignment',req('GET','/api/auth/me',token=tt))
    record('own password changed',req('POST','/api/auth/password',{'current_password':pw,'new_password':newpw},tt))
    record('old access after password change',req('GET','/api/auth/me',token=tt))
    r=req('POST','/api/auth/refresh',{'refresh_token':rt}); record('old refresh after password change',r)
    if r[0]==200: rt=r[1]['refresh_token']
    record('admin reset temporary password',req('PATCH',f'/api/users/{uid}',{'password':pw},at))
    r=req('POST','/api/auth/refresh',{'refresh_token':rt}); record('old refresh after admin password reset',r)
    if r[0]==200: rt=r[1]['refresh_token']
    record('disable temporary account',req('PATCH',f'/api/users/{uid}',{'disabled':True},at))
    record('access while disabled',req('GET','/api/auth/me',token=tt))
    record('reenable temporary account',req('PATCH',f'/api/users/{uid}',{'disabled':False},at))
    r=req('POST','/api/auth/refresh',{'refresh_token':rt}); record('old refresh after reenabling',r)
    if r[0]==200: rt=r[1]['refresh_token']
    cards=req('GET','/api/cards?page_size=1',token=tt)
    if cards[0]==200 and cards[1]['items']:
        card=cards[1]['items'][0]
        prints=req('GET',f"/api/cards/{card['id']}/printings",token=tt)
        record('printing response shape',prints,{'type':type(prints[1]).__name__,'keys':list(prints[1])[:10] if isinstance(prints[1],dict) else None})
        ps=prints[1] if isinstance(prints[1],list) else prints[1].get('items',prints[1].get('printings',[]))
        if ps:
            p=ps[0]
            record('test printing metadata',prints,{'printing':p})
            finish=p['finishes'][0]; finish=finish['code'] if isinstance(finish,dict) else finish
            language=p['languages'][0]; language=language['code'] if isinstance(language,dict) else language
            r=req('POST','/api/collection/adjust',{'printing_id':p['id'],'finish':finish,'language':language,'delta':1},tt)
            record('create temporary collection item',r)
            if r[0]==200:
                owned=r[1]['item']['id']; tx=r[1]['transaction_id']
                for method,path,body in [('GET',f'/api/collection/items/{owned}',None),('PATCH',f'/api/collection/items/{owned}',{'notes':'audit forbidden'}),('POST',f'/api/collection/transactions/{tx}/undo',{})]:
                    record('cross-account '+method+' '+path,req(method,path,body,ut))
                record('write harmless formula',req('PATCH',f'/api/collection/items/{owned}',{'notes':'=1+1'},tt))
                r=req('GET','/api/collection/export.csv',token=tt)
                record('CSV formula exported',r,{'csv':r[1]})
                record('delete temporary item',req('DELETE',f'/api/collection/items/{owned}',token=tt)); owned=None
    statuses=[]; start=time.monotonic()
    for _ in range(12): statuses.append(req('POST','/api/auth/login',{'username':name,'password':'audit-wrong-password'})[0])
    record('12 sequential failed logins',(200,{},{}),{'statuses':statuses,'seconds':round(time.monotonic()-start,2)})
    record('correct login after failures',(200,{},{}),{'successful':bool(login(name,pw).get('access_token'))})
    record('logout',req('POST','/api/auth/logout',{'refresh_token':rt}))
    record('refresh after logout',req('POST','/api/auth/refresh',{'refresh_token':rt}))
    record('access after logout',req('GET','/api/auth/me',token=tt))
finally:
    if uid: record('cleanup temporary account',req('DELETE',f'/api/users/{uid}',token=at))
    for tokens in [u,a]: record('cleanup audit login',req('POST','/api/auth/logout',{'refresh_token':tokens['refresh_token']}))
    Path('/tmp/zukan-audit-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
