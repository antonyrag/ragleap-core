if `REDIS_URL` is unset.`
        -> `**Ciw swyddi cefndir dewisol.** Mae'r swydd cydweddu integreiddio cyfnodol yn rhedeg yn fewnol yn y broses API yn ddiofyn. Mae gosod `REDIS_URL` yn ei newid i giw Redis go iawn (RQ) yn lle hynny, wedi'i brosesu gan broses(au) `worker` ar wahân sy'n graddio'n annibynnol — yn llorweddol trwy `docker compose up -d --scale worker=N`, neu yn Kubernetes trwy awtograddiwr dyfnder-ciw fel KEDA (gweler `examples/keda-scaledobject-worker.yaml` am gyfeiriad `ScaledObject`). Yn hollol ddewisol — nid oes dim yn newid os yw `REDIS_URL` heb ei osod.`

    *   `### Repo structure` -> `### Strwythur y gadwrfa`
        *   Translate comments in the structure:
        *   `# RAG engine — chunking, embedding, retrieval, generation` -> `# Injan RAG — darnio, mewnosod, adalw, cynhyrchu`
        *   `# Gemini embeddings (gemini-embedding-001, 3072-dim)` -> `# Mewnosodiadau Gemini (gemini-embedding-001, 307
