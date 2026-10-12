from pathlib import Path
from sqlalchemy import select
from app.db.models import Document
from tests.test_workbench import _client, _login


def test_hot_markdown_upload_is_listed_private_and_pending_vectorization(tmp_path):
    text='# 热点新闻\n\n## 摘要\n\n中文摘要\n\n## 完整内容\n\n整理后的正文。\n\n## 原始来源\n\n- [发布说明](<https://example.com/news>)\n'
    with _client(tmp_path) as client:
        alice,bob=_login(client,'alice'),_login(client,'bob')
        response=client.post('/api/v1/documents',headers=alice,files={'file':('热点新闻.md',text.encode('utf-8'),'text/markdown;charset=utf-8')},data={'domain':'personal_learning'})
        assert response.status_code==201,response.text
        document=response.json()
        assert document['status']=='uploaded' and document['chunks']==document['indexedChunks']==0
        assert document['filename']=='热点新闻.md' and document['title']=='热点新闻'
        assert client.get('/api/v1/documents',headers=alice).json()['items'][0]['id']==document['id']
        assert client.get('/api/v1/documents',headers=bob).json()['items']==[]
        with client.app.state.session_factory() as db:
            row=db.scalar(select(Document).where(Document.id==document['id']))
            assert Path(row.storage_path).read_text(encoding='utf-8')==text
            assert Path(row.storage_path).is_relative_to(tmp_path/'documents')
