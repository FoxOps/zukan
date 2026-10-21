from pathlib import Path
exec((Path(__file__).parent / 'reproduce.py').read_text().split('userpw=')[0])
adminpw=getpass.getpass('codex_admin password: ')
a=login('codex_admin',adminpw); at=a['access_token']; uid=None
try:
    name='audit_tmp_'+secrets.token_hex(5); pw=secrets.token_urlsafe(32)
    r=req('POST','/api/users',{'username':name,'password':pw},at)
    assert r[0]==201; uid=r[1]['id']
    t=login(name,pw); tt=t['access_token']
    r=req('POST','/api/auth/login',{'username':name,'password':pw,'mode':'cookie'},headers={'X-TCG-CSRF':'1'})
    cookie='tcg_access='+tt
    record('cookie attributes',r,{'attributes':r[2]['set-cookie'].split(';')[1:]})
    record('cookie me',req('GET','/api/auth/me',headers={'Cookie':cookie}))
    record('cookie write without CSRF',req('PATCH','/api/auth/me',{},headers={'Cookie':cookie}))
    record('cookie write with CSRF',req('PATCH','/api/auth/me',{},headers={'Cookie':cookie,'X-TCG-CSRF':'1'}))
    record('cookie login without CSRF',req('POST','/api/auth/login',{'username':name,'password':pw,'mode':'cookie'}))
    record('cookie refresh without CSRF',req('POST','/api/auth/refresh',{},headers={'Cookie':cookie}))
    record('invalid bearer',req('GET','/api/auth/me',token='audit.invalid.token'))
    record('SQL search probe',req('GET',"/api/cards?q=%27%20OR%201%3D1--&page_size=1",token=tt),{'result':'status only'})
    for field in ['NaN','1']:
        content='game,set_code,collector_number,quantity,manual_price\nmtg,UNH,23,1,'+field+'\n'
        raw=('--auditboundary\r\nContent-Disposition: form-data; name="file"; filename="audit.csv"\r\nContent-Type: text/csv\r\n\r\n'+content+'\r\n--auditboundary--\r\n').encode()
        record('CSV dry run price '+field,req('POST','/api/collection/import?dry_run=true',token=tt,headers={'Content-Type':'multipart/form-data; boundary=auditboundary'},raw=raw))
    record('temporary account empty',req('GET','/api/collection',token=tt))
    record('logout followup token',req('POST','/api/auth/logout',{'refresh_token':t['refresh_token']}))
finally:
    if uid: record('cleanup followup account',req('DELETE',f'/api/users/{uid}',token=at))
    record('cleanup followup admin login',req('POST','/api/auth/logout',{'refresh_token':a['refresh_token']}))
    Path('/tmp/zukan-audit-followup.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
