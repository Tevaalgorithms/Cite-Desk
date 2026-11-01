"""Wires the concrete parts together. This is the only module that imports both
ingestion and the answer flow, so the two stay independent of each other.
"""

from dataclasses import dataclass

from citedesk.answer.cache import AnswerCache
from citedesk.answer.rerankers import OverlapReranker
from citedesk.answer.retrieval import HybridRetriever
from citedesk.answer.service import AnswerService
from citedesk.answer.writers import ExtractiveAnswerWriter
from citedesk.config import Settings
from citedesk.domain.models import ModelHealth, ModelInfo, UsageSnapshot
from citedesk.domain.ports import (
    AnswerWriter,
    Embedder,
    ModelStatus,
    Reranker,
    VectorIndex,
)
from citedesk.indexing import sync_vector_index
from citedesk.ingestion.fetching import UrlFetcher
from citedesk.ingestion.service import IngestionService
from citedesk.storage.dev_adapters import HashingEmbedder, InMemoryVectorIndex
from citedesk.storage.repository import SqlRepository
from citedesk.tracing import Tracer


@dataclass(frozen=True)
class App:
    ingestion: IngestionService
    answers: AnswerService
    repository: SqlRepository
    # Exposed so the evaluation code can measure each retrieval stage on its own.
    embedder: Embedder
    index: VectorIndex
    reranker: Reranker
    model: ModelStatus  # describes and checks whichever writer is in use
    tracer: Tracer
    prompt_version: str = "none"  # fingerprint of the writer's prompt, as in trace metadata


def build_app(settings: Settings | None = None, *, writer: AnswerWriter | None = None) -> App:
    """Build the whole app from settings.

    At start the vector index is repaired to match the database (see `sync_vector_index`), so a
    restarted in-memory index or a drifted Pinecone index is refilled before the first question.
    Pass `writer` to replace the answer writer chosen by the settings (used by tests).
    """
    settings = settings or Settings()
    repository = SqlRepository.from_url(settings.database_url)
    tracer = build_tracer(settings)
    embedder, reranker = build_models(settings)
    chosen_writer = writer or build_writer(settings, tracer)
    index = build_index(settings, embedder)
    sync_vector_index(repository, embedder, index)

    retriever = HybridRetriever(
        embedder,
        index,
        reranker,
        candidate_limit=settings.candidate_limit,
        rerank_pool=settings.rerank_pool,
        final_limit=settings.final_passage_limit,
    )
    model = _model_status(chosen_writer)
    description = model.info()
    # Anything that changes what an answer says must be part of the cache label.
    cache_label = "|".join(
        [description.writer, description.model, settings.models, str(settings.relevance_threshold)]
    )
    return App(
        ingestion=IngestionService(
            repository,
            embedder,
            index,
            UrlFetcher(),
            chunk_max_chars=settings.chunk_max_chars,
            min_document_chars=settings.min_document_chars,
        ),
        answers=AnswerService(
            repository,
            retriever,
            chosen_writer,
            min_relevance=settings.relevance_threshold,
            max_attempts=settings.max_answer_attempts,
            cache=AnswerCache(settings.answer_cache_size, settings.answer_cache_ttl_seconds),
            cache_label=cache_label,
            tracer=tracer,
            trace_metadata={
                "environment": settings.environment,
                "writer": description.writer,
                "model": description.model,
                "models": settings.models,
                "vector_index": settings.vector_index,
                "prompt_version": _prompt_version(description),
            },
        ),
        repository=repository,
        embedder=embedder,
        index=index,
        reranker=reranker,
        model=model,
        tracer=tracer,
        prompt_version=_prompt_version(description),
    )


def describe_retrieval(settings: Settings) -> str:
    """One sentence about how passages are found, for the model status bar's tooltip."""
    models = (
        "Embeddings: bge-small-en-v1.5. Reranker: ms-marco MiniLM. Both run locally."
        if settings.models == "local"
        else "Embeddings and reranker: word-matching stand-ins (no models)."
    )
    vectors = (
        f"Vectors: Pinecone ({settings.pinecone_index}, namespace {settings.vector_namespace})."
        if settings.vector_index == "pinecone"
        else "Vectors: in memory."
    )
    return f"{models} {vectors}"


def build_tracer(settings: Settings) -> Tracer:
    """A LangSmith tracer if CITEDESK_LANGSMITH_TRACING is on, otherwise one that does nothing."""
    if not settings.langsmith_tracing:
        return Tracer()
    if settings.langsmith_api_key is None:
        raise RuntimeError(
            "CITEDESK_LANGSMITH_TRACING=true needs CITEDESK_LANGSMITH_API_KEY to be set."
        )
    return Tracer.create(
        settings.langsmith_api_key.get_secret_value(),
        settings.langsmith_project,
        hide_content=settings.langsmith_hide_content,
    )


def _prompt_version(description: ModelInfo) -> str:
    """Fingerprint of the writer's prompt, or "none" for a writer that has no prompt."""
    if description.writer != "openai":
        return "none"
    from citedesk.adapters.openai_writer import PROMPT_VERSION

    return PROMPT_VERSION


def build_writer(settings: Settings, tracer: Tracer | None = None) -> AnswerWriter:
    """The answer writer chosen by CITEDESK_WRITER."""
    if settings.writer == "openai":
        if settings.openai_api_key is None:
            raise RuntimeError("CITEDESK_WRITER=openai needs CITEDESK_OPENAI_API_KEY to be set.")
        # Imported here so the extractive writer works without calling OpenAI at all.
        from openai import OpenAI

        from citedesk.adapters.openai_writer import OpenAIAnswerWriter

        client = OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.openai_timeout_seconds,
            max_retries=1,
        )
        return OpenAIAnswerWriter(
            (tracer or Tracer()).wrap_openai(client),
            settings.openai_model,
            max_output_tokens=settings.openai_max_output_tokens,
            retrieval_description=describe_retrieval(settings),
        )
    return ExtractiveAnswerWriter()


class _PlainModelStatus:
    """Status for a writer that cannot describe itself (for example a test double)."""

    def info(self) -> ModelInfo:
        return ModelInfo(writer="custom", provider="custom", model="custom", description="")

    def check(self) -> ModelHealth:
        return ModelHealth(state="offline", detail="This writer does not report its status")

    def usage(self) -> UsageSnapshot | None:
        return None


def _model_status(writer: AnswerWriter) -> ModelStatus:
    return writer if isinstance(writer, ModelStatus) else _PlainModelStatus()


def build_index(settings: Settings, embedder: Embedder) -> VectorIndex:
    """The vector index chosen by CITEDESK_VECTOR_INDEX."""
    if settings.vector_index == "pinecone":
        if settings.pinecone_api_key is None:
            raise RuntimeError(
                "CITEDESK_VECTOR_INDEX=pinecone needs CITEDESK_PINECONE_API_KEY to be set."
            )
        # Imported here so the in-memory index works without touching the Pinecone SDK.
        from pinecone import Pinecone

        from citedesk.adapters.pinecone_index import PineconeVectorIndex, ensure_index

        client = Pinecone(api_key=settings.pinecone_api_key.get_secret_value())
        host = ensure_index(
            client,
            settings.pinecone_index,
            dimension=embedder.dimension,
            cloud=settings.pinecone_cloud,
            region=settings.pinecone_region,
        )
        return PineconeVectorIndex(client.Index(host=host), settings.vector_namespace)
    return InMemoryVectorIndex()


def build_models(settings: Settings) -> tuple[Embedder, Reranker]:
    """The embedding model and reranker for the chosen backend."""
    if settings.models == "local":
        # Imported here so the offline backend works without the optional `models` extra.
        from citedesk.adapters.local_models import CrossEncoderReranker, FastEmbedEmbedder

        return FastEmbedEmbedder(), CrossEncoderReranker()
    return HashingEmbedder(), OverlapReranker()
