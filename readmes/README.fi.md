se siirretään todelliseen Redis-jonoon (RQ), jota käsittelevät erilliset `worker`-prosessit. Nämä skaalautuvat itsenäisesti — vaakasuunnassa komennolla `docker compose up -d --scale worker=N` tai Kubernetesissa jonon pituuteen perustuvalla automaattisella skaalaimella, kuten KEDA (katso mallina `examples/keda-scaledobject-worker.yaml` tiedoston `ScaledObject`). Täysin valinnainen — mikään ei muutu, jos `REDIS_URL` ei ole asetettu."

    *   **Repo structure**:
        *   `### Repo structure` -> `### Repositorion rakenne`
        *   Translate the comments in the tree:
            *   `# RAG engine — chunking, embedding, retrieval, generation` -> `# RAG-moottori — palastelu, upotus, haku, generointi`
            *   `# Gemini embeddings (gemini-embedding-001, 3072-dim)` -> `# Gemini-upotukset (gemini-embedding-001, 3072-ulotteinen)`
            *   `# pgvector cosine search` -> `# pgvector-kosinihaku`
            *   `# 19-provider BYOK generation (Gemini, OpenAI, Anthropic, etc.)` -> `# 19 tarjoajan BYOK-generointi (
