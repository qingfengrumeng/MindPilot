from tests.test_workbench import _client, _login


def test_batch_delete_is_atomic_owner_scoped_and_cleans_links(tmp_path):
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        path='/api/v1/workbench/items'
        def create(headers,kind,title,links=[]):
            return client.post(path,headers=headers,json={'kind':kind,'title':title,'links':links}).json()
        first=create(alice,'hot','热点一');second=create(alice,'hot','热点二');foreign=create(bob,'hot','其他用户热点')
        wiki=create(alice,'wiki','关联记录',[first['id'],second['id']])
        assert client.post(path+'/batch-delete',json={'ids':[first['id']]}).status_code==401
        assert client.post(path+'/batch-delete',headers=alice,json={'ids':[]}).status_code==422
        assert client.post(path+'/batch-delete',headers=alice,json={'ids':[first['id'],foreign['id']]}).status_code==404
        assert client.get(path+'/'+first['id'],headers=alice).status_code==200
        assert client.post(path+'/batch-delete',headers=alice,json={'ids':[first['id'],'missing']}).status_code==404
        response=client.post(path+'/batch-delete',headers=alice,json={'ids':[first['id'],second['id'],first['id']]})
        assert response.status_code==200,response.text
        assert response.json()['deleted']==2
        assert set(response.json()['deletedIds'])=={first['id'],second['id']}
        assert client.get(path+'/'+wiki['id'],headers=alice).json()['links']==[]
        assert client.get(path+'?kind=hot',headers=alice).json()['total']==0
        assert client.get(path+'/'+foreign['id'],headers=bob).status_code==200
        client.put('/api/v1/workbench/hot-preferences',headers=alice,json={'direction':'科技'})
        with client.app.state.session_factory() as db:
            from sqlalchemy import select
            from app.db.models import WorkbenchEntry
            internal=db.scalar(select(WorkbenchEntry).where(WorkbenchEntry.kind=='hot-preferences'))
            internal_id=internal.id
        assert client.post(path+'/batch-delete',headers=alice,json={'ids':[wiki['id'],internal_id]}).status_code==404
        assert client.get(path+'/'+wiki['id'],headers=alice).status_code==200
