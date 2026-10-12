from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import perf_counter_ns

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from app.api.routes import agent_tasks, auth, conversation_map, conversations, diagrams, documents, embeddings, files, images, posters, rerank, search, speech, speech_live, workbench
from app.core.config import Settings, load_settings
from app.core.storage_layout import prepare_business_directories
from app.db.session import make_engine
from app.db.models import Document
from app.services.document_jobs import ACTIVE_DOCUMENT_STATUSES
from app.services.conversation_titles import ConversationTitleQueue, install_first_turn_hook
from app.services.session_journal import SessionJournal
from app.services.conversation_context import ConversationContext
from app.services.long_term_memory import LongTermMemory
from app.runtime.agent_registry import AgentRegistry
from app.runtime.agent_runner import AgentRunner
from app.runtime.artifacts import ArtifactStore
from app.runtime.skill_registry import SkillRegistry
from app.runtime.task_manager import TaskManager
from app.tools.runtime_tools import make_tool_registry
from app.api.routes import model_configs
from app.api.routes import rag_evaluations
from app.api.routes import evaluation_reports
from app.db.models import DocumentWikiCompilation, WikiSupplementJob, KnowledgeGraphIndex
from app.api.routes import knowledge_graph
from app.api.routes import memories as memory_routes


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = make_engine(settings)
    factory = sessionmaker(engine, expire_on_commit=False)
    install_first_turn_hook(factory)
    journal = SessionJournal(settings, factory)
    journal.install()
    memories = LongTermMemory(journal, settings, factory)
    conversation_context = ConversationContext(journal, memories)
    title_queue = ConversationTitleQueue(factory, workers=2, model_config_path=settings.model_config_path)
    document_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mindpilot-document")
    wiki_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mindpilot-wiki")
    graph_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mindpilot-graph")
    hot_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="mindpilot-hot")
    tool_registry = make_tool_registry()
    agent_registry = AgentRegistry(tool_registry)
    agent_registry.discover()
    skill_registry = SkillRegistry()
    skill_registry.discover()
    task_manager = TaskManager(factory)
    artifact_store = ArtifactStore(factory, settings.data_dir)
    agent_runner = AgentRunner(agent_registry, tool_registry, skill_registry, task_manager,
                               artifact_store, settings, factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        prepare_business_directories(settings)
        migration_config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        migration_config.attributes["database_url"] = settings.database_url
        with engine.connect() as connection:
            migration_config.attributes["connection"] = connection
            command.upgrade(migration_config, "head")
        journal.files.policy()
        journal.backfill()
        task_manager.recover_interrupted()
        title_queue.start()
        memories.start()
        with factory() as db:
            rag_evaluations.cleanup(settings, db)
            db.execute(update(DocumentWikiCompilation).where(DocumentWikiCompilation.status.in_(('queued','compiling'))).values(status='failed',error_message='服务重启中断了Wiki编译，请重新点击编译按钮。'))
            db.execute(update(WikiSupplementJob).where(WikiSupplementJob.status.in_(('queued', 'running')))
                       .values(status='failed', error_message='服务重启中断了Wiki补充，下次检索可重新尝试。'))
            db.execute(update(KnowledgeGraphIndex).where(KnowledgeGraphIndex.status.in_(('queued', 'building')))
                       .values(status='failed', error_message='服务重启中断图谱构建，请重新构建。'))
            db.execute(
                update(Document)
                .where(Document.status.in_(ACTIVE_DOCUMENT_STATUSES))
                .values(status="failed", error_message="服务重启中断了处理，请重新点击向量化")
            )
            db.commit()
        try:
            yield
        finally:
            memories.shutdown()
            title_queue.shutdown()
            document_executor.shutdown(wait=True, cancel_futures=True)
            wiki_executor.shutdown(wait=True, cancel_futures=True)
            graph_executor.shutdown(wait=True, cancel_futures=True)
            hot_executor.shutdown(wait=True)
            agent_runner.shutdown()
            engine.dispose()

    app = FastAPI(title="MindPilot API", version="0.1.0", lifespan=lifespan)
    app.state.title_queue = title_queue
    app.state.settings = settings
    app.state.session_journal = journal
    app.state.memories = memories
    app.state.conversation_context = conversation_context
    app.state.session_factory = factory
    app.state.document_executor = document_executor
    app.state.wiki_executor = wiki_executor
    app.state.graph_executor = graph_executor
    app.state.hot_executor = hot_executor
    app.state.hot_jobs = {}
    app.state.tool_registry = tool_registry
    app.state.agent_registry = agent_registry
    app.state.skill_registry = skill_registry
    app.state.task_manager = task_manager
    app.state.artifact_store = artifact_store
    app.state.agent_runner = agent_runner
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        issue = exc.errors()[0]
        field = str(issue.get("loc", [""])[-1])
        label = {"baseUrl": "接口地址", "apiKey": "API Key", "model": "模型名称", "username": "用户名", "password": "密码", "category": "模型类别"}.get(field, "提交信息")
        message = f"请填写{label}" if issue["type"] == "missing" else f"{label}格式不符合要求，请检查后重试"
        return JSONResponse({"detail": message}, status_code=422)

    @app.middleware("http")
    async def protect_cookie_endpoints(request: Request, call_next):
        request.state.received_ns = perf_counter_ns()
        if request.method in {"POST", "PATCH", "DELETE"} and request.url.path.startswith("/api/v1/auth/"):
            origin = request.headers.get("origin")
            if origin and origin not in settings.allowed_origins:
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "不允许的请求来源"}, status_code=403)
        return await call_next(request)

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(model_configs.router, prefix="/api/v1")
    app.include_router(rag_evaluations.router, prefix="/api/v1")
    app.include_router(evaluation_reports.router, prefix="/api/v1")
    app.include_router(memory_routes.router, prefix="/api/v1")
    app.include_router(agent_tasks.router, prefix="/api/v1")
    app.include_router(conversations.router, prefix="/api/v1")
    app.include_router(conversation_map.router, prefix="/api/v1")
    app.include_router(diagrams.router, prefix="/api/v1")
    app.include_router(posters.router, prefix="/api/v1")
    app.include_router(files.router, prefix="/api/v1")
    app.include_router(documents.router, prefix="/api/v1")
    app.include_router(knowledge_graph.router, prefix="/api/v1")
    app.include_router(workbench.router, prefix="/api/v1")
    app.include_router(search.router, prefix="/api/v1")
    app.include_router(embeddings.router, prefix="/api/v1")
    app.include_router(images.router, prefix="/api/v1")
    app.include_router(rerank.router, prefix="/api/v1")
    app.include_router(speech.router, prefix="/api/v1")
    app.include_router(speech_live.router, prefix="/api/v1")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
