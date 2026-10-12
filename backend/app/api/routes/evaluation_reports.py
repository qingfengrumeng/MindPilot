"""Explicit permanent snapshots, isolated from expiring RAG workspaces."""
from datetime import datetime, timezone
import json
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.api.deps import CurrentContext
from app.core.storage_layout import business_directory

router=APIRouter(prefix='/model-evaluations/reports',tags=['model-evaluations'])

class ReportInput(BaseModel):
    kind:str=Field(pattern='^(llm|rag)$')
    title:str=Field(min_length=1,max_length=160)
    result:dict

def root(request,user_id):
    return business_directory(request.app.state.settings,'model_comparisons','saved_reports',str(UUID(user_id)))

@router.post('')
def save_report(payload:ReportInput,request:Request,context:CurrentContext):
    encoded=json.dumps(payload.result,ensure_ascii=False)
    if len(encoded.encode('utf-8'))>20*1024*1024:
        raise HTTPException(422,'报告超过20MB，请减少评测规模')
    # A report must never contain saved or supplied authentication material.
    def has_secret(value):
        if isinstance(value,dict):
            return any(str(key).lower().replace('_','') in {'apikey','speechapikey','accesskey','authorization','accesstoken','refreshtoken','credentials'} or has_secret(item) for key,item in value.items())
        return isinstance(value,list) and any(has_secret(item) for item in value)
    if has_secret(payload.result):
        raise HTTPException(422,'报告不能包含密钥或认证字段')
    report={'id':str(uuid4()),'kind':payload.kind,'title':payload.title,'createdAt':datetime.now(timezone.utc).isoformat(),'result':payload.result}
    path=root(request,context[0].id)/(report['id']+'.json')
    temporary=path.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return report

@router.get('')
def list_reports(request:Request,response:Response,context:CurrentContext):
    response.headers['Cache-Control']='no-store'
    items=[]
    for path in root(request,context[0].id).glob('*.json'):
        try:report=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):continue
        if not all(key in report for key in ('id','kind','title','createdAt')):continue
        items.append({key:report[key] for key in ('id','kind','title','createdAt')})
    return {'items':sorted(items,key=lambda item:item['createdAt'],reverse=True)}

@router.get('/{report_id}')
def get_report(report_id:str,request:Request,context:CurrentContext):
    try: name=str(UUID(report_id))
    except ValueError: raise HTTPException(404,'测试报告不存在') from None
    path=root(request,context[0].id)/(name+'.json')
    if not path.exists(): raise HTTPException(404,'测试报告不存在')
    return json.loads(path.read_text(encoding='utf-8'))

@router.delete('/{report_id}')
def remove_report(report_id:str,request:Request,context:CurrentContext):
    get_report(report_id,request,context)
    (root(request,context[0].id)/(str(UUID(report_id))+'.json')).unlink()
    return {'deleted':True}
