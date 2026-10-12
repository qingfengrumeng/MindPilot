from tests.test_workbench import _client, _login


def test_hot_preferences_are_persistent_private_business_records(tmp_path):
    with _client(tmp_path) as client:
        alice, bob = _login(client,'alice'), _login(client,'bob')
        path = '/api/v1/workbench/hot-preferences'
        assert client.get(path).status_code == 401
        assert client.get(path,headers=alice).json() == {'direction':'', 'maxItems':30}
        prefs = {'direction':'研究与论文、医疗 RAG', 'maxItems':12}
        response = client.put(path,headers=alice,json=prefs)
        assert response.status_code == 200, response.text
        assert client.get(path,headers=alice).json() == prefs
        assert client.get(path,headers=bob).json()['direction'] == ''
        assert client.get('/api/v1/workbench/items',headers=alice).json()['items'] == []
        assert client.get('/api/v1/workbench/system',headers=alice).json()['entries'] == 0
        assert client.put(path,headers=alice,json={**prefs,'direction':'a'*1001}).status_code == 422
        assert client.put(path,headers=alice,json={**prefs,'maxItems':0}).status_code == 422
    with _client(tmp_path) as client:
        alice = _login(client,'alice')
        assert client.get(path,headers=alice).json() == prefs


def test_empty_limit_is_unlimited_and_old_preferences_are_migrated(tmp_path):
    with _client(tmp_path) as client:
        alice = _login(client,'alice')
        path = '/api/v1/workbench/hot-preferences'
        migrated = client.put(path,headers=alice,json={'topics':['研究与论文','医疗'], 'keywords':'RAG', 'lookbackDays':3, 'maxItems':12})
        assert migrated.json() == {'direction':'研究与论文；医疗；RAG', 'maxItems':12}
        for value in [None, '']:
            response = client.put(path,headers=alice,json={'direction':' 医疗 AI ', 'maxItems':value})
            assert response.status_code == 200
            assert response.json() == {'direction':'医疗 AI', 'maxItems':None}
        assert client.put(path,headers=alice,json={'maxItems':101}).status_code == 422
    with _client(tmp_path) as client:
        alice = _login(client,'alice')
        assert client.get(path,headers=alice).json() == {'direction':'医疗 AI', 'maxItems':None}


def test_viewed_state_is_owner_scoped_idempotent_and_pagination_is_complete(tmp_path):
    with _client(tmp_path) as client:
        alice, bob = _login(client,'alice'), _login(client,'bob')
        path = '/api/v1/workbench/items'
        records = [client.post(path,headers=alice,json={'kind':'hot','title':f'热点{index}', 'data':{'sourceUrl':'https://example.com','externalId':str(index)}}).json() for index in range(3)]
        target = records[1]
        assert not target['data'].get('viewedAt')
        view_path = f"{path}/{target['id']}/viewed"
        assert client.post(view_path,headers=bob).status_code == 404
        updated = client.post(view_path,headers=alice).json()
        assert updated['data']['viewedAt']
        assert updated['data']['externalId'] == '1'
        assert client.post(view_path,headers=alice).json()['data']['viewedAt'] == updated['data']['viewedAt']
        first = client.get(path+'?kind=hot&limit=2',headers=alice).json()
        last = client.get(path+'?kind=hot&limit=2&offset=2',headers=alice).json()
        assert first['total'] == last['total'] == 3
        assert len({item['id'] for item in first['items']+last['items']}) == 3
        assert client.get(path+'?offset=-1',headers=alice).status_code == 422
        assert client.get(path+'?kind=hot',headers=bob).json()['total'] == 0
