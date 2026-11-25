"""End-to-end test against isolated synthetic DB and live loopback services."""
import base64,io,json,os,time,urllib.request,urllib.error,zipfile
from pathlib import Path
PORT=int(os.environ.get('DMT_PORT','32173'))
BASE='http://127.0.0.1:'+str(PORT)
MANAGER='jsaiclass.duckdns.org';ORIGIN='https://'+MANAGER
PREFIX='/dmtwebapp/api/'
def req(path,body=None,cookie=None,host=MANAGER,origin=ORIGIN,headers=None):
    h={'Host':host,**(headers or {})}
    if body is not None:
        h['Origin']=origin
        if isinstance(body,dict):body=json.dumps(body).encode();h['Content-Type']='application/json'
    if cookie:h['Cookie']=cookie
    q=urllib.request.Request(BASE+path,data=body,headers=h)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    try:r=urllib.request.build_opener(NoRedirect).open(q,timeout=30)
    except urllib.error.HTTPError as e:r=e
    with r:return r.status,dict(r.headers),r.read()
def obj(resp,status):
    assert resp[0]==status,(resp[0],resp[2][:160]);return json.loads(resp[2])
def login(phone):
    r=req(PREFIX+'login',{'phone':phone});obj(r,200);return r[1]['Set-Cookie'].split(';')[0]
def upload(c,blob,name,folder='findone',config=None):
    meta={'filename':name,'folder':folder,'name':'FinDone test','title':'Trial','notes':'Synthetic data','config':config or {}}
    return obj(req(PREFIX+'upload',blob,c,headers={'Content-Type':'application/zip','X-DMT-Meta':base64.b64encode(json.dumps(meta).encode()).decode()}),202)['version']
def ready(c,v,folder='findone'):
    end=time.monotonic()+180
    while time.monotonic()<end:
        s=obj(req(PREFIX+'me',cookie=c),200);a=next(a for a in s['apps'] if a['folder']==folder);u=next(u for u in a['versions'] if u['version']==v)
        if u['state']=='ready':return a,u
        assert u['state']!='failed',u.get('error')
        time.sleep(1)
    raise AssertionError('BUILD_TIMEOUT')
def static(txt):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('index.html','<!doctype html><title>Test</title>'+txt)
    return b.getvalue()
def main():
    assert req('/dmtwebapp/')[0]==200
    obj(req(PREFIX+'me'),401);obj(req(PREFIX+'login',{'phone':'0700000999'}),401)
    c=login('0700000011');c2=login('0700000022')
    assert obj(req(PREFIX+'me',cookie=c),200)['folder']=='0011'
    assert req('/dmtwebapp/0011/',cookie=c2)[0]==403
    assert req('/dmtwebapp/0011/',cookie=c)[0]==200
    assert req(PREFIX+'logout',{},c,origin='https://bad.example')[0]==403
    print('LOGIN_SESSION_ORIGIN_SCOPE_OK',flush=True)
    blob=Path(os.environ['DMT_FINDONE_ZIP']).read_bytes();t=time.monotonic()
    v=upload(c,blob,'findone.zip');a,u=ready(c,v)
    assert v==1 and a['active']==1 and u['database']=='browser'
    host=a['host'];r=req('/dmtwebapp/0011/findone/');assert r[0]==302 and r[1]['Location']=='https://'+host+'/'
    r=req('/',host=host);assert r[0]==302 and r[1]['Location']=='/__dmt_versions/1/'
    r=req('/__dmt_versions/1/',host=host);assert r[0]==200 and b'FinDone' in r[2]
    assert req('/__dmt_versions/1/original.zip',host=host)[0]==404
    assert req(PREFIX+'me',cookie=c,host=host)[0]==404
    r=req('/internal/tls?domain='+host,host='127.0.0.1:'+str(PORT));assert obj(r,200)['allowed']
    assert req('/internal/tls?domain=unknown.example',host='127.0.0.1:'+str(PORT))[0]==403
    assert obj(req(PREFIX+'me',cookie=c2),200)['apps']==[]
    assert req(PREFIX+'serve',{'folder':'findone','version':1},c2)[0]==409
    assert req('/dmtwebapp/0011/findone/versions/1/',cookie=c2)[0]==403
    print('FINDONE_SHARED_BUILD_AND_ORIGIN_OK',round(time.monotonic()-t,2),flush=True)
    t=time.monotonic();v2=upload(c,blob,'duplicate.zip');a,u=ready(c,v2);assert v2==2 and a['active']==1
    print('IDENTICAL_ZIP_READY_SECONDS',round(time.monotonic()-t,2),flush=True)
    obj(req(PREFIX+'serve',{'folder':'findone','version':2},c),200)
    assert req('/',host=host)[1]['Location']=='/__dmt_versions/2/'
    assert req(PREFIX+'delete',{'folder':'findone','version':2},c)[0]==409
    obj(req(PREFIX+'rollback',{'folder':'findone','version':1},c),200)
    obj(req(PREFIX+'delete',{'folder':'findone','version':2},c),200)
    assert req('/__dmt_versions/2/',host=host)[0]==404
    assert req('/__dmt_versions/1/',host=host)[0]==200
    print('VERSION_LIFECYCLE_OK',flush=True)
    v=upload(c,static('managed demo'),'managed.zip','managed',{'mode':'managed'});a,u=ready(c,v,'managed');h=a['host']
    r=req('/__dmt_data',{'op':'put','key':'tasks','value':['one']},host=h,origin='https://'+h);obj(r,200);b=r[1]['Set-Cookie'].split(';')[0]
    assert obj(req('/__dmt_data',{'op':'get','key':'tasks'},b,h,'https://'+h),200)['value']==['one']
    assert obj(req('/__dmt_data',{'op':'get','key':'tasks'},host=h,origin='https://'+h),200)['value'] is None
    assert req('/__dmt_data',{'op':'put','key':'tasks','value':['two']},b,h,'https://evil.example')[0]==403
    obj(req(PREFIX+'delete_app',{'folder':'managed'},c),200)
    assert req('/',host=h)[0]==404
    print('MANAGED_DB_BROWSER_ISOLATION_OK',flush=True)
    obj(req(PREFIX+'logout',{},c),200);obj(req(PREFIX+'me',cookie=c),401)
    print('STAGING_E2E_PASS',flush=True)
if __name__=='__main__':main()
