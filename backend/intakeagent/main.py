"""FastAPI application factory.

``create_app`` wires every component from settings so tests can build an isolated app with
an in-memory SQLite database and the stub providers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from intakeagent import __version__
from intakeagent.api import rest, ws
from intakeagent.api.service import IntakeService
from intakeagent.config import Settings, get_settings
from intakeagent.db.engine import create_db_engine, init_db
from intakeagent.db.rag import HashingEmbeddings, OpenAICompatibleEmbeddings, build_store
from intakeagent.db.seed_protocols import hint_for, seed_protocols
from intakeagent.exporters import ClioExporter, ClioOAuthClient, FhirExporter
from intakeagent.graph import build_intake_graph
from intakeagent.graph.extractors import build_extractor
from intakeagent.llm import resolve_provider
from intakeagent.schemas import LegalIntake, PatientIntake
from intakeagent.stt import get_stt_provider

log = logging.getLogger("intakeagent")


def build_exporters(settings: Settings) -> dict[str, Any]:
    fhir = FhirExporter(settings.fhir_base_url, push=settings.fhir_push and not settings.demo_mode)
    clio = ClioExporter(
        settings.clio_base_url,
        access_token="" if settings.demo_mode else settings.clio_access_token,
    )

    def export_fhir(vertical: str, record: dict[str, Any], session_id: str) -> dict[str, Any]:
        if vertical != "healthcare":
            return {"target": "fhir", "error": "FHIR export is only available for healthcare"}
        return fhir.export(PatientIntake(**record), session_id)

    def export_clio(vertical: str, record: dict[str, Any], session_id: str) -> dict[str, Any]:
        if vertical != "legal":
            return {"target": "clio", "error": "Clio export is only available for legal"}
        return clio.export(LegalIntake(**record), session_id)

    return {"fhir": export_fhir, "clio": export_clio}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_db_engine(settings.database_url)
        init_db(engine)

        llm = resolve_provider(settings)
        if llm.is_stub or llm.provider == "groq":
            embeddings = HashingEmbeddings()
        else:
            embeddings = OpenAICompatibleEmbeddings(
                llm.base_url or "", llm.api_key, "nomic-embed-text"
            )
        store = build_store(engine, embeddings)
        try:
            added = seed_protocols(store)
            if added:
                log.info("Seeded %d protocol snippets", added)
        except Exception:  # embeddings endpoint down: hints are optional
            log.exception("Protocol seeding failed; continuing without hints")

        extractor = build_extractor(llm, allow_cloud=settings.allow_cloud_llm)
        exporters = build_exporters(settings)

        def hints(vertical: str, field_name: str) -> str | None:
            try:
                return hint_for(store, vertical, field_name)
            except Exception:
                return None

        graph = build_intake_graph(extractor, exporters, hint_lookup=hints)

        app.state.settings = settings
        app.state.engine = engine
        app.state.llm = llm
        app.state.stt = get_stt_provider(settings)
        app.state.service = IntakeService(engine, graph, exporters)
        log.info(
            "IntakeAgent ready: demo=%s llm=%s stt=%s db=%s",
            settings.demo_mode,
            llm.provider,
            app.state.stt.name,
            settings.database_url.split("@")[-1],
        )
        yield
        engine.dispose()

    app = FastAPI(
        title="IntakeAgent",
        version=__version__,
        description="Voice-first intake agent with FHIR R4 and Clio exports and mandatory HITL.",
        lifespan=lifespan,
    )
    # CORS must be registered before the routers so preflight (OPTIONS) requests are answered
    # by the middleware. Origins come from CORS_ORIGINS. WebSocket upgrades are not subject to
    # CORS; the browser sends an Origin header which a reverse proxy or auth layer can check.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        max_age=600,
    )
    app.include_router(rest.router)
    app.include_router(ws.router)

    @app.get("/health")
    def health(request: Request) -> dict[str, Any]:
        st = request.app.state
        return {
            "status": "ok",
            "version": __version__,
            "demo_mode": st.settings.demo_mode,
            "llm": st.llm.provider,
            "llm_local": st.llm.is_local,
            "stt": st.stt.name,
            "fhir_push": st.settings.fhir_push,
            "clio_mode": "live"
            if st.settings.clio_configured and not st.settings.demo_mode
            else "mock",
        }

    # --- Clio OAuth2 helper endpoints ------------------------------------------------
    @app.get("/oauth/clio/authorize")
    def clio_authorize(request: Request) -> RedirectResponse:
        st: Settings = request.app.state.settings
        if not (st.clio_client_id and st.clio_client_secret):
            raise HTTPException(400, "CLIO_CLIENT_ID and CLIO_CLIENT_SECRET are not configured")
        client = ClioOAuthClient(
            st.clio_base_url, st.clio_client_id, st.clio_client_secret, st.clio_redirect_uri
        )
        url, _state = client.authorize_url()
        return RedirectResponse(url)

    @app.get("/oauth/clio/callback")
    def clio_callback(code: str, request: Request) -> dict[str, Any]:
        st: Settings = request.app.state.settings
        client = ClioOAuthClient(
            st.clio_base_url, st.clio_client_id, st.clio_client_secret, st.clio_redirect_uri
        )
        token = client.exchange_code(code)
        # Tokens are returned once for the operator to place in their secret store.
        return {
            "message": "Set CLIO_ACCESS_TOKEN and CLIO_REFRESH_TOKEN in your environment.",
            "access_token": token.access_token,
            "refresh_token": token.refresh_token,
            "expires_in": token.expires_in,
        }

    return app


app = create_app()
